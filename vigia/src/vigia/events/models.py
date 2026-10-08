"""Modelo de evento compartilhado por todas as regras (permanência, porta, moto, rosto...)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

Severity = Literal["info", "alerta", "critico"]

SEVERITY_ICON = {"info": "ℹ️", "alerta": "⚠️", "critico": "🚨"}


@dataclass
class Event:
    kind: str  # "loitering" | "face_known" | "face_unknown" | "unidentified" | ...
    camera_id: str
    message: str
    severity: Severity = "alerta"
    zone: str | None = None
    track_id: int | None = None
    bbox: tuple[int, int, int, int] | None = None
    subject: str | None = None  # quem: nome reconhecido (entra no cooldown)
    timestamp: float = field(default_factory=time.time)  # wall clock (para exibir)
    frame: np.ndarray | None = field(default=None, repr=False)  # já anotado
    meta: dict = field(default_factory=dict)

    @property
    def dedup_key(self) -> str:
        """Chave de cooldown. Sem track_id de propósito: se o tracker trocar o ID
        da mesma pessoa, não queremos um segundo alerta da mesma zona. O `subject`
        (nome reconhecido) entra: "Ana chegou" não pode calar "Bia chegou"."""
        key = f"{self.camera_id}:{self.kind}:{self.zone or '-'}"
        return f"{key}:{self.subject}" if self.subject else key
