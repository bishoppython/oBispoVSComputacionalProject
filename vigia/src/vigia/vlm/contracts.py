"""Contrato da fase 4. O VLM só roda DEPOIS que uma regra disparou — nunca por frame.

Modelo sugerido: Qwen2.5-VL 3B (Q4) no Ollama; alternativas: Gemma 3 4B, Moondream 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class SceneVerdict:
    suspicious: bool
    confidence: float  # 0..1
    description: str  # frase curta em PT-BR para a legenda do Telegram


class SceneVerifier(Protocol):
    def verify(self, crop: np.ndarray, question: str, timeout_s: float = 8.0) -> SceneVerdict: ...
