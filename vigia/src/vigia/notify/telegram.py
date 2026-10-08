"""Envio de alertas ao Telegram (sendPhoto) numa thread separada.

O loop de vídeo nunca espera a rede: os eventos entram numa fila.
"""

from __future__ import annotations

import html
import logging
import queue
import threading
import time
from datetime import datetime

import cv2
import httpx
import numpy as np

from vigia.events.models import SEVERITY_ICON, Event

log = logging.getLogger(__name__)
API = "https://api.telegram.org/bot{token}/{method}"


class TelegramClient:
    def __init__(self, token: str, chat_id: str, timeout: float = 15.0):
        self.token = token
        self.chat_id = chat_id
        self._http = httpx.Client(timeout=timeout)

    def _url(self, method: str) -> str:
        return API.format(token=self.token, method=method)

    def send_message(self, text: str) -> None:
        r = self._http.post(
            self._url("sendMessage"),
            data={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
        )
        r.raise_for_status()

    def send_photo(self, image: np.ndarray, caption: str) -> None:
        self.send_photo_bytes(encode_jpeg(image), caption)

    def send_photo_bytes(self, jpeg: bytes, caption: str) -> None:
        r = self._http.post(
            self._url("sendPhoto"),
            data={"chat_id": self.chat_id, "caption": caption[:1024], "parse_mode": "HTML"},
            files={"photo": ("alerta.jpg", jpeg, "image/jpeg")},
        )
        r.raise_for_status()

    def send_document(self, content: bytes, filename: str, caption: str, mimetype: str) -> None:
        r = self._http.post(
            self._url("sendDocument"),
            data={"chat_id": self.chat_id, "caption": caption[:1024], "parse_mode": "HTML"},
            files={"document": (filename, content, mimetype)},
        )
        r.raise_for_status()

    def close(self) -> None:
        self._http.close()


def encode_jpeg(image: np.ndarray, quality: int = 85) -> bytes:
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("Falha ao codificar JPEG")
    return buf.tobytes()


def format_caption(event: Event) -> str:
    when = datetime.fromtimestamp(event.timestamp).strftime("%d/%m/%Y %H:%M:%S")
    lines = [
        f"{SEVERITY_ICON[event.severity]} <b>Alerta de suspeito</b>",
        html.escape(event.message),
        "",
        f"📷 {html.escape(event.camera_id)}"
        + (f" · zona <code>{html.escape(event.zone)}</code>" if event.zone else ""),
        f"🕒 {when}",
    ]
    return "\n".join(lines)


class TelegramNotifier:
    """EventSink assíncrono com retentativas."""

    def __init__(self, client: TelegramClient, max_queue: int = 50, retries: int = 3):
        self.client = client
        self.retries = retries
        self._q: queue.Queue[Event | None] = queue.Queue(maxsize=max_queue)
        self._thread = threading.Thread(target=self._worker, name="telegram", daemon=True)
        self._thread.start()

    def handle(self, event: Event) -> None:
        try:
            self._q.put_nowait(event)
        except queue.Full:
            log.error("Fila do Telegram cheia; evento descartado: %s", event.dedup_key)

    def _send(self, event: Event) -> None:
        caption = format_caption(event)
        if event.frame is not None:
            self.client.send_photo(event.frame, caption)
        else:
            self.client.send_message(caption)

    def _worker(self) -> None:
        while True:
            event = self._q.get()
            if event is None:
                return
            for attempt in range(1, self.retries + 1):
                try:
                    self._send(event)
                    break
                except Exception as exc:
                    log.warning("Telegram falhou (tentativa %d/%d): %s", attempt, self.retries, exc)
                    time.sleep(2 * attempt)

    def close(self) -> None:
        self._q.put(None)
        self._thread.join(timeout=10)
        self.client.close()
