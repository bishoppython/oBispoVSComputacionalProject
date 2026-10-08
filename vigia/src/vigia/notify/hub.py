"""Envio dos eventos ao hub do homelab, com fila em disco e heartbeat.

O evento é gravado em `outbox/` antes de qualquer rede: se o homelab estiver fora
do ar, nada se perde e o envio é refeito depois. O hub descarta duplicados pelo
`id`, então reenviar é seguro.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import httpx

from vigia.events.models import Event
from vigia.notify.telegram import encode_jpeg

log = logging.getLogger(__name__)


def event_to_payload(event: Event, event_id: str) -> dict:
    """Serializa o evento (sem o frame) para JSON."""
    return {
        "id": event_id,
        "kind": event.kind,
        "camera_id": event.camera_id,
        "message": event.message,
        "severity": event.severity,
        "zone": event.zone,
        "track_id": event.track_id,
        "bbox": list(event.bbox) if event.bbox else None,
        "timestamp": event.timestamp,
        "meta": json.loads(json.dumps(event.meta, default=str)),
    }


class HubClient:
    def __init__(self, url: str, token: str, timeout: float = 10.0):
        self._http = httpx.Client(
            base_url=url.rstrip("/"),
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}"},
        )

    def post_event(self, payload: dict, jpeg: bytes | None) -> None:
        files = {"photo": ("alerta.jpg", jpeg, "image/jpeg")} if jpeg else None
        r = self._http.post("/events", data={"event": json.dumps(payload)}, files=files)
        r.raise_for_status()

    def post_heartbeat(self, status: dict) -> None:
        r = self._http.post("/heartbeat", json=status)
        r.raise_for_status()

    def close(self) -> None:
        self._http.close()


class Outbox:
    """Fila persistente: um `.json` (+ `.jpg` opcional) por evento, em ordem de chegada."""

    def __init__(self, directory: Path, max_items: int = 500):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.max_items = max_items

    def put(self, payload: dict, jpeg: bytes | None) -> Path:
        stem = f"{time.time_ns()}_{payload['id']}"
        if jpeg:
            (self.directory / f"{stem}.jpg").write_bytes(jpeg)
        tmp = self.directory / f"{stem}.json.tmp"
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        path = tmp.rename(self.directory / f"{stem}.json")  # o .json só aparece completo
        self._trim()
        return path

    def pending(self) -> list[Path]:
        return sorted(self.directory.glob("*.json"))

    def load(self, path: Path) -> tuple[dict, bytes | None]:
        jpg = path.with_suffix(".jpg")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload, jpg.read_bytes() if jpg.exists() else None

    def remove(self, path: Path) -> None:
        path.with_suffix(".jpg").unlink(missing_ok=True)
        path.unlink(missing_ok=True)

    def _trim(self) -> None:
        items = self.pending()
        for old in items[: max(0, len(items) - self.max_items)]:
            log.error("Outbox cheia; descartando evento antigo %s", old.name)
            self.remove(old)


class HubSink:
    """EventSink que entrega ao hub em segundo plano e manda heartbeat periódico."""

    def __init__(
        self,
        client: HubClient,
        outbox: Outbox,
        heartbeat_s: float = 60.0,
        retry_s: float = 30.0,
        status_fn: Callable[[], dict] | None = None,
        clock: Callable[[], float] = time.monotonic,
        autostart: bool = True,
    ):
        self.client = client
        self.outbox = outbox
        self.heartbeat_s = heartbeat_s
        self.retry_s = retry_s
        self.status_fn = status_fn
        self._clock = clock
        self._node = socket.gethostname()
        self._retry_at = 0.0
        self._next_heartbeat = 0.0
        self._hub_ok = True
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if pending := len(self.outbox.pending()):
            log.info("Outbox com %d evento(s) pendente(s) de envio ao hub.", pending)
        if autostart:
            self._thread = threading.Thread(target=self._worker, name="hub", daemon=True)
            self._thread.start()

    def handle(self, event: Event) -> None:
        jpeg = encode_jpeg(event.frame) if event.frame is not None else None
        self.outbox.put(event_to_payload(event, uuid.uuid4().hex), jpeg)
        self._retry_at = 0.0  # tenta já, mesmo se estava em espera
        self._wake.set()

    def flush(self) -> bool:
        """Envia os pendentes em ordem. Para no primeiro erro (o hub deve estar fora)."""
        for path in self.outbox.pending():
            try:
                payload, jpeg = self.outbox.load(path)
                self.client.post_event(payload, jpeg)
            except (httpx.HTTPError, OSError) as exc:
                self._set_hub_ok(False, exc)
                return False
            self.outbox.remove(path)
            self._set_hub_ok(True)
        return True

    def step(self, now: float) -> None:
        """Uma iteração do worker (separada para os testes controlarem o tempo)."""
        if now >= self._retry_at and not self.flush():
            self._retry_at = now + self.retry_s
        if self.status_fn is not None and now >= self._next_heartbeat:
            self._next_heartbeat = now + self.heartbeat_s
            try:
                self.client.post_heartbeat({"node": self._node, **self.status_fn()})
                self._set_hub_ok(True)
            except httpx.HTTPError as exc:
                self._set_hub_ok(False, exc)

    def _set_hub_ok(self, ok: bool, exc: Exception | None = None) -> None:
        if ok and not self._hub_ok:
            log.info("Hub de volta; envios retomados.")
        elif not ok and self._hub_ok:
            log.warning("Hub inacessível (%s); eventos ficam na outbox.", exc)
        self._hub_ok = ok

    def _worker(self) -> None:
        while not self._stop.is_set():
            self.step(self._clock())
            self._wake.wait(timeout=1.0)
            self._wake.clear()

    def close(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=10)
        self.flush()  # última tentativa; o que falhar fica para a próxima execução
        self.client.close()
