"""Alarme sonoro no alto-falante do homelab (ALSA, via `aplay`).

A sirene é gerada por código (sem arquivo de áudio no repositório). Toca em loop
até `alarm_duration_s` ou até alguém silenciar pelo painel.
"""

from __future__ import annotations

import io
import logging
import shutil
import subprocess
import threading
import time
import wave
from collections.abc import Callable
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)


def siren_wav(seconds: float = 3.0, rate: int = 22050) -> bytes:
    """Sirene "wail": frequência sobe e desce entre 650 e 1300 Hz."""
    t = np.arange(int(seconds * rate)) / rate
    sweep = 650 + 650 * (0.5 - 0.5 * np.cos(2 * np.pi * t / 1.5))
    phase = 2 * np.pi * np.cumsum(sweep) / rate
    wave_ = 0.8 * np.sign(np.sin(phase)) * 0.35 + 0.65 * np.sin(phase)  # mais áspera, mais alta
    pcm = (np.clip(wave_, -1, 1) * 32000).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


class Alarm:
    """Estado do alarme (o painel lê) + reprodução opcional no alto-falante."""

    def __init__(
        self,
        data_dir: Path,
        duration_s: float = 30.0,
        device: str | None = None,
        play_sound: bool = True,
        clock: Callable[[], float] = time.time,
        volume: int | None = 100,
        mixer: str = "Master",
        card: int = 0,
    ):
        self.duration_s = duration_s
        self.device = device
        self.volume = volume
        self.mixer = mixer
        self.card = card
        self._clock = clock
        self.active_since: float | None = None
        self.reason = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._wav: Path | None = None
        if play_sound:
            if shutil.which("aplay") is None:
                log.warning("`aplay` não encontrado: alarme só no painel.")
            else:
                self._wav = Path(data_dir) / "sirene.wav"
                self._wav.parent.mkdir(parents=True, exist_ok=True)
                self._wav.write_bytes(siren_wav())

    @property
    def active(self) -> bool:
        if self.active_since is None:
            return False
        if self._clock() - self.active_since > self.duration_s:
            self.active_since = None
        return self.active_since is not None

    def state(self) -> dict:
        return {"active": self.active, "since": self.active_since, "reason": self.reason}

    def trigger(self, reason: str) -> None:
        with self._lock:
            log.warning("🔊 ALARME: %s", reason)
            self.reason = reason
            already = self.active
            self.active_since = self._clock()  # novo gatilho estende o alarme
            if already or self._wav is None:
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._play, name="alarm", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            if self.active_since is not None:
                log.info("Alarme silenciado.")
            self.active_since = None
            self._stop.set()

    def _raise_volume(self) -> None:
        """O homelab pode estar com o volume zerado/mudo: o alarme precisa ser ouvido."""
        if self.volume is None or shutil.which("amixer") is None:
            return
        level = f"{self.volume}%"
        cmd = ["amixer", "-q", "-c", str(self.card), "sset", self.mixer, level, "unmute"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            log.warning("Não consegui ajustar o volume (%s): %s", self.mixer, result.stderr.strip())

    def _play(self) -> None:
        self._raise_volume()
        cmd = ["aplay", "-q"] + (["-D", self.device] if self.device else []) + [str(self._wav)]
        while self.active and not self._stop.is_set():
            try:
                proc = subprocess.Popen(cmd, stderr=subprocess.PIPE)
                while proc.poll() is None:
                    if self._stop.wait(0.2) or not self.active:
                        proc.terminate()
                        return
                if proc.returncode != 0:
                    err = proc.stderr.read().decode(errors="replace").strip() if proc.stderr else ""
                    log.error("aplay falhou (%s): %s", proc.returncode, err)
                    return
            except OSError as exc:
                log.error("Não foi possível tocar o alarme: %s", exc)
                return
