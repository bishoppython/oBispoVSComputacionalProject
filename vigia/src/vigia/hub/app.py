"""API HTTP do hub (só na LAN, autenticada por token)."""

from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from vigia.hub.report import previous_month
from vigia.hub.service import Hub

MAX_PHOTO_BYTES = 8 * 1024 * 1024


class EventIn(BaseModel):
    id: str = Field(pattern=r"^[0-9a-f]{32}$")  # vira nome de arquivo: só hex
    kind: str = Field(max_length=40)
    camera_id: str = Field(max_length=60)
    message: str = Field(max_length=1000)
    severity: str = Field(pattern=r"^(info|alerta|critico)$")
    zone: str | None = Field(default=None, max_length=60)
    track_id: int | None = None
    bbox: list[int] | None = None
    timestamp: float
    meta: dict = {}


class HeartbeatIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    node: str = Field(max_length=100)
    camera_ok: bool | None = None
    fps: float | None = None


def create_app(hub: Hub, token: str) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        hub.start()
        yield
        hub.stop()

    app = FastAPI(title="Vigia hub", lifespan=lifespan)

    def auth(authorization: Annotated[str, Header()] = "") -> None:
        expected = f"Bearer {token}".encode()
        if not secrets.compare_digest(authorization.encode(), expected):
            raise HTTPException(status_code=401, detail="token inválido")

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "node_online": hub.node.online,
            "node": hub.node_status,
            "camera_online": hub.camera.online if hub.camera_probe else None,
            "events": hub.store.count(),
            "channels": [c.name for c in hub.channels],
        }

    @app.post("/events", dependencies=[Depends(auth)])
    async def events(
        event: Annotated[str, Form()], photo: Annotated[UploadFile | None, File()] = None
    ) -> dict:
        try:
            data = EventIn.model_validate_json(event)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422, detail=exc.errors(include_url=False, include_context=False)
            ) from exc
        jpeg = await photo.read(MAX_PHOTO_BYTES + 1) if photo else None
        if jpeg and len(jpeg) > MAX_PHOTO_BYTES:
            raise HTTPException(status_code=413, detail="foto grande demais")
        created = hub.ingest(data.model_dump(), jpeg or None)
        return {"status": "ok" if created else "duplicate"}

    @app.post("/heartbeat", dependencies=[Depends(auth)])
    def heartbeat(body: HeartbeatIn) -> dict:
        hub.heartbeat(body.model_dump())
        return {"status": "ok"}

    @app.post("/reports/monthly", dependencies=[Depends(auth)])
    def monthly_report(month: str | None = None) -> dict:
        """Gera e envia o relatório. `month=AAAA-MM`; padrão: mês anterior."""
        if month:
            try:
                year, m = (int(p) for p in month.split("-"))
                date(year, m, 1)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="use month=AAAA-MM") from exc
        else:
            year, m = previous_month(date.today())
        return hub.send_monthly_report(year, m)

    @app.post("/notify/test", dependencies=[Depends(auth)])
    def notify_test() -> dict:
        hub.notify_text("✅ Teste do Vigia hub: este canal está funcionando.")
        return {"status": "ok", "channels": [c.name for c in hub.channels]}

    return app
