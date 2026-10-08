"""API HTTP do hub (só na LAN).

- Nitro: token `Authorization: Bearer` (eventos, heartbeat, galeria).
- Painel: senha (`HUB_PANEL_PASSWORD`) -> cookie assinado; as rotas /api/* aceitam
  o cookie ou o token.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated

import cv2
import numpy as np
from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from vigia.hub.live import BOUNDARY, LiveRelay
from vigia.hub.report import previous_month
from vigia.hub.service import Hub

MAX_PHOTO_BYTES = 8 * 1024 * 1024
MAX_UPLOADS = 20
SESSION_COOKIE = "vigia_sessao"
SESSION_S = 30 * 86400
STATIC = Path(__file__).parent / "static"


class EventIn(BaseModel):
    id: str = Field(pattern=r"^[0-9a-f]{32}$")  # vira nome de arquivo: só hex
    kind: str = Field(max_length=40)
    camera_id: str = Field(max_length=60)
    message: str = Field(max_length=1000)
    severity: str = Field(pattern=r"^(info|alerta|critico)$")
    zone: str | None = Field(default=None, max_length=60)
    subject: str | None = Field(default=None, max_length=60)
    track_id: int | None = None
    bbox: list[int] | None = None
    timestamp: float
    meta: dict = {}


class HeartbeatIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    node: str = Field(max_length=100)
    camera_ok: bool | None = None
    fps: float | None = None


class PersonIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class PhotoStatusIn(BaseModel):
    status: str = Field(pattern=r"^(pending|ok|sem_rosto)$")


def _normalize_jpeg(data: bytes) -> bytes:
    """Decodifica e recodifica: valida a imagem e remove metadados (EXIF/GPS)."""
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=422, detail="arquivo não é uma imagem válida")
    h, w = img.shape[:2]
    if max(h, w) > 1920:  # foto de celular: reduz (o rosto continua grande)
        scale = 1920 / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()


def create_app(
    hub: Hub,
    token: str,
    panel_password: str | None = None,
    live: dict[str, LiveRelay] | None = None,
    capture: Callable[[int, float], list[bytes]] | None = None,
) -> FastAPI:
    live = live or {}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        hub.start()
        yield
        hub.stop()

    app = FastAPI(title="Vigia hub", lifespan=lifespan, docs_url=None, redoc_url=None)

    # ---- autenticação ------------------------------------------------------
    def _bearer_ok(authorization: str) -> bool:
        expected = f"Bearer {token}".encode()
        return secrets.compare_digest(authorization.encode(), expected)

    def _sign(exp: int) -> str:
        return hmac.new(token.encode(), f"painel:{exp}".encode(), hashlib.sha256).hexdigest()

    def _session_ok(cookie: str | None) -> bool:
        if not cookie or "." not in cookie:
            return False
        exp, sig = cookie.split(".", 1)
        if not exp.isdigit() or int(exp) < time.time():
            return False
        return secrets.compare_digest(sig.encode(), _sign(int(exp)).encode())

    def auth(authorization: Annotated[str, Header()] = "") -> None:
        if not _bearer_ok(authorization):
            raise HTTPException(status_code=401, detail="token inválido")

    def user(
        authorization: Annotated[str, Header()] = "",
        vigia_sessao: Annotated[str | None, Cookie()] = None,
    ) -> None:
        if not (_bearer_ok(authorization) or _session_ok(vigia_sessao)):
            raise HTTPException(status_code=401, detail="faça login no painel")

    # ---- painel (páginas) --------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def panel(vigia_sessao: Annotated[str | None, Cookie()] = None):
        if not _session_ok(vigia_sessao):
            return RedirectResponse("/login", status_code=303)
        return FileResponse(STATIC / "panel.html")

    @app.get("/login", response_class=HTMLResponse)
    def login_page():
        return FileResponse(STATIC / "login.html")

    @app.post("/login")
    def login(password: Annotated[str, Form()] = ""):
        if not panel_password:
            return RedirectResponse("/login?erro=config", status_code=303)
        if not secrets.compare_digest(password.encode(), panel_password.encode()):
            time.sleep(1.0)  # freia tentativa e erro
            return RedirectResponse("/login?erro=senha", status_code=303)
        exp = int(time.time()) + SESSION_S
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(
            SESSION_COOKIE,
            f"{exp}.{_sign(exp)}",
            max_age=SESSION_S,
            httponly=True,
            samesite="strict",
        )
        return resp

    @app.post("/logout")
    def logout():
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(SESSION_COOKIE)
        return resp

    # ---- Nitro ---------------------------------------------------------------
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
            detail = exc.errors(include_url=False, include_context=False)
            raise HTTPException(status_code=422, detail=detail) from exc
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

    # ---- painel (API) --------------------------------------------------------
    api = [Depends(user)]

    @app.get("/api/state", dependencies=api)
    def state() -> dict:
        return {
            "now": time.time(),
            "node_online": hub.node.online,
            "node": hub.node_status,
            "camera_online": hub.camera.online if hub.camera_probe else None,
            "alarm": hub.alarm.state(),
            "channels": [c.name for c in hub.channels],
            "people": [
                {"name": p["name"], "ok": sum(f["status"] == "ok" for f in p["photos"])}
                for p in hub.store.people()
            ],
        }

    @app.get("/api/events", dependencies=api)
    def list_events(limit: int = 50, since: float | None = None) -> list[dict]:
        return [e.to_dict() for e in hub.store.recent(max(1, min(limit, 200)), since)]

    @app.get("/api/events/{event_id}/photo.jpg", dependencies=api)
    def event_photo(event_id: str):
        ev = hub.store.get(event_id)
        path = hub.store.data_dir / ev.photo if ev and ev.photo else None
        if path is None or not path.exists():
            raise HTTPException(status_code=404)
        return FileResponse(path, media_type="image/jpeg")

    @app.post("/api/alarm/stop", dependencies=api)
    def alarm_stop() -> dict:
        hub.alarm.stop()
        return hub.alarm.state()

    @app.post("/api/alarm/test", dependencies=api)
    def alarm_test() -> dict:
        hub.alarm.trigger("Teste do alarme pelo painel")
        return hub.alarm.state()

    @app.get("/api/live.mjpg", dependencies=api)
    def live_video(src: str = "vigia"):
        relay = live.get(src)
        if relay is None:
            raise HTTPException(status_code=404, detail="fonte de vídeo desconhecida")
        return StreamingResponse(
            relay.stream(), media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}"
        )

    # ---- cadastro de rostos ---------------------------------------------------
    @app.get("/api/faces/manifest", dependencies=api)
    @app.get("/api/people", dependencies=api)
    def people() -> dict:
        return {"people": hub.store.people()}

    @app.post("/api/people", dependencies=api)
    def add_person(body: PersonIn) -> dict:
        name = " ".join(body.name.split())
        if not name:
            raise HTTPException(status_code=422, detail="nome vazio")
        return {"id": hub.store.add_person(name), "name": name}

    @app.delete("/api/people/{person_id}", dependencies=api)
    def delete_person(person_id: int) -> dict:
        if not hub.store.delete_person(person_id):
            raise HTTPException(status_code=404)
        return {"status": "ok"}

    def _person_exists(person_id: int) -> None:
        if not any(p["id"] == person_id for p in hub.store.people()):
            raise HTTPException(status_code=404, detail="pessoa não encontrada")

    @app.post("/api/people/{person_id}/photos", dependencies=api)
    async def upload_photos(person_id: int, request: Request) -> dict:
        _person_exists(person_id)
        form = await request.form()
        files = [f for f in form.getlist("files") if hasattr(f, "read")][:MAX_UPLOADS]
        if not files:
            raise HTTPException(status_code=422, detail="nenhuma foto enviada")
        ids = []
        for f in files:
            data = await f.read(MAX_PHOTO_BYTES + 1)
            if len(data) > MAX_PHOTO_BYTES:
                raise HTTPException(status_code=413, detail=f"{f.filename}: grande demais")
            ids.append(hub.store.add_face_photo(person_id, _normalize_jpeg(data), "upload"))
        return {"added": ids}

    @app.post("/api/people/{person_id}/capture", dependencies=api)
    def capture_photos(person_id: int, count: int = 8, interval: float = 0.6) -> dict:
        _person_exists(person_id)
        if capture is None:
            raise HTTPException(status_code=503, detail="captura pela câmera indisponível")
        try:
            frames = capture(max(1, min(count, 20)), max(0.2, min(interval, 3.0)))
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        ids = [hub.store.add_face_photo(person_id, f, "camera") for f in frames]
        return {"added": ids}

    @app.get("/api/faces/photos/{photo_id}.jpg", dependencies=api)
    def face_photo(photo_id: str):
        path = hub.store.face_photo_path(photo_id)
        if path is None or not path.exists():
            raise HTTPException(status_code=404)
        return FileResponse(path, media_type="image/jpeg")

    @app.post("/api/faces/photos/{photo_id}/status", dependencies=api)
    def face_photo_status(photo_id: str, body: PhotoStatusIn) -> dict:
        if not hub.store.set_face_photo_status(photo_id, body.status):
            raise HTTPException(status_code=404)
        return {"status": "ok"}

    @app.delete("/api/faces/photos/{photo_id}", dependencies=api)
    def delete_face_photo(photo_id: str) -> dict:
        if not hub.store.delete_face_photo(photo_id):
            raise HTTPException(status_code=404)
        return {"status": "ok"}

    return app
