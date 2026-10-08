"""Galeria de rostos em memória (poucas pessoas: busca exata por cosseno basta)."""

from __future__ import annotations

import numpy as np

from vigia.face.contracts import FaceMatch


class MemoryGallery:
    def __init__(self) -> None:
        self._names: list[str] = []
        self._sources: list[str] = []
        self._embs: list[np.ndarray] = []
        self._matrix: np.ndarray | None = None

    def add(self, person: str, embedding: np.ndarray, source: str) -> None:
        emb = np.asarray(embedding, dtype=np.float32)
        self._names.append(person)
        self._sources.append(source)
        self._embs.append(emb / (np.linalg.norm(emb) + 1e-9))
        self._matrix = None

    def __len__(self) -> int:
        return len(self._embs)

    @property
    def sources(self) -> list[str]:
        return list(self._sources)

    @property
    def people(self) -> list[str]:
        return sorted(set(self._names))

    def best(self, embedding: np.ndarray) -> tuple[str | None, float]:
        """Pessoa mais parecida (máximo entre as fotos de cada um) e a similaridade."""
        if not self._embs:
            return None, 0.0
        if self._matrix is None:
            self._matrix = np.stack(self._embs)
        emb = np.asarray(embedding, dtype=np.float32)
        sims = self._matrix @ (emb / (np.linalg.norm(emb) + 1e-9))
        i = int(np.argmax(sims))
        return self._names[i], float(sims[i])

    def match(self, embedding: np.ndarray, threshold: float) -> FaceMatch:
        name, sim = self.best(embedding)
        return FaceMatch(person=name if sim >= threshold else None, similarity=sim)
