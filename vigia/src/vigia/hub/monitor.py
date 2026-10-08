"""Detecção de "sinal de vida": Nitro (heartbeat) e câmera (mediamtx).

Lógica pura com tempo injetado: só reporta TRANSIÇÕES, para que desligar a
Nitro gere um único aviso, e não um a cada verificação.
"""

from __future__ import annotations

from typing import Literal

Transition = Literal["online", "offline"]


class PresenceMonitor:
    def __init__(self, offline_after_s: float, started_at: float):
        self.offline_after_s = offline_after_s
        self.started_at = started_at
        self.last_seen: float | None = None
        self.online: bool | None = None  # None = ainda não sabemos

    @property
    def last_signal(self) -> float:
        """Último sinal de vida; se nunca houve, o início do monitoramento."""
        return self.last_seen if self.last_seen is not None else self.started_at

    def beat(self, now: float) -> Transition | None:
        """Registra um sinal de vida. Retorna "online" se estava offline."""
        self.last_seen = now
        was = self.online
        self.online = True
        return "online" if was is False else None

    def check(self, now: float) -> Transition | None:
        """Retorna "offline" na primeira verificação após o limite sem sinal."""
        if self.online is False:
            return None
        if now - self.last_signal > self.offline_after_s:
            self.online = False
            return "offline"
        return None
