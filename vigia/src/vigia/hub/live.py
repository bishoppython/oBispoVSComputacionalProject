"""Vídeo para o painel: lê o RTSP do mediamtx e serve MJPEG atrás do login.

Só roda enquanto alguém está assistindo (o i3 do homelab agradece) e para
sozinho `idle_s` depois do último acesso.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator

import cv2
import numpy as np

log = logging.getLogger(__name__)
BOUNDARY = "quadro"


class LiveRelay:
    def __init__(self, url: str, name: str, max_fps: float = 10.0, idle_s: float = 20.0):
        self.url = url
        self.name = name
        self.max_fps = max_fps
        self.idle_s = idle_s
        self._jpeg: bytes | None = None
        self._seq = 0
        self._last_access = 0.0
        self._cond = threading.Condition()
        self._thread: threading.Thread | None = None

    def _ensure_running(self) -> None:
        self._last_access = time.monotonic()
        if self._thread is None or not self._thread.is_alive():
            name = f"live-{self.name}"
            self._thread = threading.Thread(target=self._loop, name=name, daemon=True)
            self._thread.start()

    def _loop(self) -> None:
        log.info("Painel: abrindo vídeo '%s'.", self.name)
        cap = None
        interval = 1.0 / self.max_fps
        last = 0.0
        while time.monotonic() - self._last_access < self.idle_s:
            if cap is None:
                cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
                if not cap.isOpened():
                    cap.release()
                    cap = None
                    time.sleep(3)
                    continue
            ok, frame = cap.read()
            if not ok:
                cap.release()
                cap = None
                continue
            now = time.monotonic()
            if now - last < interval:
                continue
            last = now
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ok:
                with self._cond:
                    self._jpeg = buf.tobytes()
                    self._seq += 1
                    self._cond.notify_all()
        if cap is not None:
            cap.release()
        with self._cond:
            self._jpeg = None
        log.info("Painel: vídeo '%s' fechado (ninguém assistindo).", self.name)

    def stream(self) -> Iterator[bytes]:
        """Gerador multipart/x-mixed-replace (um por espectador)."""
        seen = 0
        while True:
            self._ensure_running()
            with self._cond:
                self._cond.wait_for(lambda last=seen: self._seq != last, timeout=5)
                jpeg, seen = self._jpeg, self._seq
            if jpeg is None:
                continue
            yield (
                (
                    f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                    f"Content-Length: {len(jpeg)}\r\n\r\n"
                ).encode()
                + jpeg
                + b"\r\n"
            )


def capture_frames(url: str, count: int, interval_s: float, timeout_s: float = 15.0) -> list[bytes]:
    """Captura `count` frames do RTSP espaçados por `interval_s` (cadastro pela câmera)."""
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    frames: list[bytes] = []
    try:
        if not cap.isOpened():
            raise RuntimeError("não foi possível abrir a câmera")
        deadline = time.monotonic() + timeout_s
        next_t = time.monotonic() + 1.0  # descarta o primeiro segundo (keyframe/exposição)
        while len(frames) < count and time.monotonic() < deadline:
            ok, frame = cap.read()
            if not ok:
                continue
            if time.monotonic() >= next_t:
                frames.append(_jpeg(frame))
                next_t = time.monotonic() + interval_s
    finally:
        cap.release()
    return frames


def _jpeg(frame: np.ndarray) -> bytes:
    return cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()
