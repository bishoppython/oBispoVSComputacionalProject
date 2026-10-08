"""Publica o vídeo ANOTADO (caixas, nomes, zonas) no mediamtx do homelab.

É o que o painel mostra ao vivo: dá para conferir se a detecção e o reconhecimento
estão certos. Roda numa thread com ffmpeg (NVENC na Nitro); o loop de vídeo só
entrega o frame mais recente e nunca espera. Se o ffmpeg cair, é reiniciado.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time

import numpy as np

from vigia.video.source import mask_source

log = logging.getLogger(__name__)


class LivePublisher:
    def __init__(
        self,
        url: str,
        fps: float = 15.0,
        encoder: str = "h264_nvenc",
        bitrate: str = "2M",
        restart_s: float = 5.0,
    ):
        self.url = url
        self.fps = fps
        self.encoder = encoder
        self.bitrate = bitrate
        self.restart_s = restart_s
        self._frame: np.ndarray | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._size: tuple[int, int] | None = None
        self._thread = threading.Thread(target=self._loop, name="live", daemon=True)

    def start(self) -> LivePublisher:
        self._thread.start()
        return self

    def publish(self, frame: np.ndarray) -> None:
        with self._lock:
            self._frame = frame

    def _command(self, w: int, h: int) -> list[str]:
        codec = ["-c:v", self.encoder]
        if self.encoder.endswith("nvenc"):
            codec += ["-preset", "p1", "-tune", "ll"]
        elif self.encoder == "libx264":
            codec += ["-preset", "ultrafast", "-tune", "zerolatency"]
        return [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", str(self.fps),
            "-i", "-",
            *codec, "-b:v", self.bitrate, "-g", str(int(self.fps * 2)), "-pix_fmt", "yuv420p",
            "-f", "rtsp", "-rtsp_transport", "tcp", self.url,
        ]  # fmt: skip

    def _open(self, w: int, h: int) -> None:
        self._close_proc()
        log.info("Publicando vídeo anotado em %s (%dx%d).", mask_source(self.url), w, h)
        self._proc = subprocess.Popen(self._command(w, h), stdin=subprocess.PIPE)
        self._size = (w, h)

    def _close_proc(self) -> None:
        if self._proc is not None:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
                self._proc.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                self._proc.kill()
            self._proc = None

    def _loop(self) -> None:
        interval = 1.0 / self.fps
        next_t = time.monotonic()
        while not self._stop.is_set():
            next_t += interval
            with self._lock:
                frame = self._frame
            if frame is not None:  # repete o último frame se não chegou outro: taxa constante
                h, w = frame.shape[:2]
                try:
                    if self._proc is None or self._proc.poll() is not None or self._size != (w, h):
                        self._open(w, h)
                    self._proc.stdin.write(np.ascontiguousarray(frame).tobytes())
                except (BrokenPipeError, OSError) as exc:
                    log.warning("Publicação do vídeo anotado caiu (%s); tentando de novo.", exc)
                    self._close_proc()
                    self._stop.wait(self.restart_s)
                    next_t = time.monotonic()
            delay = next_t - time.monotonic()
            if delay > 0:
                self._stop.wait(delay)
            else:
                next_t = time.monotonic()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)
        self._close_proc()
