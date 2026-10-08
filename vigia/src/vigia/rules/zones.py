"""Zonas poligonais em coordenadas normalizadas (0..1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import yaml

# entrance: porta por onde se entra (marca "entrou"); sensitive: área sensível (ex.: cama).
# door/vehicle entram na fase 3.
ZONE_KINDS = {"loitering", "entrance", "sensitive", "door", "vehicle"}


@dataclass
class Zone:
    name: str
    kind: str
    polygon: np.ndarray  # (N, 2) float, normalizado
    threshold_s: float | None = None
    _cache: dict[tuple[int, int], np.ndarray] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.polygon = np.asarray(self.polygon, dtype=np.float32)
        if self.polygon.ndim != 2 or self.polygon.shape[0] < 3 or self.polygon.shape[1] != 2:
            raise ValueError(f"Zona '{self.name}': polígono precisa de >= 3 pontos (x, y)")
        if self.kind not in ZONE_KINDS:
            raise ValueError(f"Zona '{self.name}': kind inválido '{self.kind}'")

    def to_pixels(self, w: int, h: int) -> np.ndarray:
        key = (w, h)
        if key not in self._cache:
            self._cache[key] = (self.polygon * np.array([w, h])).astype(np.int32)
        return self._cache[key]

    def contains(self, point: tuple[int, int], w: int, h: int) -> bool:
        pts = self.to_pixels(w, h)
        return cv2.pointPolygonTest(pts, (float(point[0]), float(point[1])), False) >= 0

    def to_dict(self) -> dict:
        d: dict = {
            "name": self.name,
            "kind": self.kind,
            "polygon": [[round(float(x), 4), round(float(y), 4)] for x, y in self.polygon],
        }
        if self.threshold_s is not None:
            d["threshold_s"] = self.threshold_s
        return d


def load_zones(path: str | Path) -> list[Zone]:
    path = Path(path)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    zones = [Zone(**z) for z in data.get("zones") or []]
    names = [z.name for z in zones]
    if len(names) != len(set(names)):
        raise ValueError(f"Nomes de zona duplicados em {path}")
    return zones


def save_zones(path: str | Path, zones: list[Zone]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"zones": [z.to_dict() for z in zones]}
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
