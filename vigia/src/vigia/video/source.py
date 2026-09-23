"""Fonte de vídeo unificada: webcam, arquivo ou RTSP (VIGI C330I).

Lê frames numa thread e mantém só o mais recente — em RTSP isso evita o
atraso acumulado quando o processamento é mais lento que a câmera.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

# RTSP via TCP é bem mais estável que UDP em Wi-Fi/redes domésticas.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")


def mask_source(source: int | str) -> str:
    """Esconde usuário/senha de URLs RTSP nos logs."""
    s = str(source)
    if "@" in s and "://" in s:
        scheme, rest = s.split("://", 1)
        return f"{scheme}://***@{rest.split('@', 1)[1]}"
    return s


class VideoSource:
    def __init__(self, source: int | str, name: str = "cam", reconnect_seconds: float = 5.0):
        self.source = source
        self.name = name
        self.reconnect_seconds = reconnect_seconds
        self.is_file = isinstance(source, str) and Path(source).is_file()

        self._cond = threading.Condition()
        self._frame: np.ndarray | None = None
        self._ts: float = 0.0
        self._seq = 0
        self._last_read_seq = 0
        self._running = False
        self._ended = False
        self._thread: threading.Thread | None = None

    # ---- ciclo de vida -------------------------------------------------
    def start(self) -> VideoSource:
        self._running = True
        self._thread = threading.Thread(target=self._loop, name=f"src-{self.name}", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._running = False
        with self._cond:
            self._cond.notify_all()
        if self._thread:
            self._thread.join(timeout=3)

    @property
    def ended(self) -> bool:
        """True quando um arquivo de vídeo chegou ao fim."""
        return self._ended

    # ---- leitura -------------------------------------------------------
    def read(self, timeout: float = 2.0) -> tuple[bool, np.ndarray | None, float]:
        """Espera por um frame NOVO. Retorna (ok, frame, timestamp_monotonic)."""
        with self._cond:
            self._cond.wait_for(
                lambda: self._seq != self._last_read_seq or not self._running or self._ended,
                timeout=timeout,
            )
            if self._frame is None or self._seq == self._last_read_seq:
                return False, None, 0.0
            self._last_read_seq = self._seq
            return True, self._frame.copy(), self._ts

    # ---- thread de captura --------------------------------------------
    def _open(self) -> cv2.VideoCapture | None:
        log.info("Abrindo fonte %s: %s", self.name, mask_source(self.source))
        cap = cv2.VideoCapture(self.source)
        if not cap.isOpened():
            log.warning("Não foi possível abrir %s", mask_source(self.source))
            cap.release()
            return None
        return cap

    def _loop(self) -> None:
        cap = None
        frame_interval = 0.0
        while self._running:
            if cap is None:
                cap = self._open()
                if cap is None:
                    time.sleep(self.reconnect_seconds)
                    continue
                if self.is_file:
                    fps = cap.get(cv2.CAP_PROP_FPS) or 25
                    frame_interval = 1.0 / fps  # reproduz arquivo em "tempo real"

            ok, frame = cap.read()
            if not ok:
                cap.release()
                cap = None
                if self.is_file:
                    log.info("Fim do arquivo de vídeo.")
                    self._ended = True
                    with self._cond:
                        self._cond.notify_all()
                    return
                log.warning(
                    "Perda de sinal em %s; reconectando em %ss", self.name, self.reconnect_seconds
                )
                time.sleep(self.reconnect_seconds)
                continue

            with self._cond:
                self._frame = frame
                self._ts = time.monotonic()
                self._seq += 1
                self._cond.notify_all()

            if frame_interval:
                time.sleep(frame_interval)

        if cap is not None:
            cap.release()


def resize_to_width(frame: np.ndarray, width: int) -> np.ndarray:
    h, w = frame.shape[:2]
    if w <= width:
        return frame
    scale = width / w
    return cv2.resize(frame, (width, int(h * scale)), interpolation=cv2.INTER_AREA)


def grab_one_frame(source: int | str, timeout: float = 10.0) -> np.ndarray:
    """Captura um único frame (usado pelo editor de zonas e pelo probe)."""
    src = VideoSource(source, name="probe").start()
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ok, frame, _ = src.read(timeout=1.0)
            if ok and frame is not None:
                return frame
        raise TimeoutError(f"Nenhum frame recebido de {mask_source(source)} em {timeout}s")
    finally:
        src.stop()
