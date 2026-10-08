"""Contratos da fase 2 (reconhecimento facial).

Implementações: `encoder.InsightFaceEncoder` (`buffalo_l`: SCRFD + ArcFace 512-d) e
`gallery.MemoryGallery` (busca exata por cosseno; poucas pessoas dispensam pgvector).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class FaceObservation:
    bbox: tuple[int, int, int, int]
    embedding: np.ndarray  # (512,) L2-normalizado
    det_score: float
    quality: float  # 0..1 (tamanho, nitidez, pose frontal)


@dataclass(frozen=True)
class FaceMatch:
    person: str | None  # None = desconhecido
    similarity: float


class FaceEncoder(Protocol):
    def encode(
        self, frame: np.ndarray, person_box: tuple[int, int, int, int]
    ) -> list[FaceObservation]: ...


class FaceGallery(Protocol):
    def add(self, person: str, embedding: np.ndarray, source: str) -> None: ...
    def match(self, embedding: np.ndarray, threshold: float) -> FaceMatch: ...
