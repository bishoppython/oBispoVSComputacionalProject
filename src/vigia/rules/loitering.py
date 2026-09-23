"""Regra de permanência: quanto tempo cada track fica em cada zona.

Lógica pura (sem OpenCV/YOLO) e com tempo injetado -> fácil de testar.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _Presence:
    first_seen: float
    last_seen: float
    alerted: bool = False


@dataclass(frozen=True)
class LoiterHit:
    zone: str
    track_id: int
    dwell_s: float


class LoiteringTracker:
    def __init__(
        self,
        thresholds: dict[str, float] | None = None,
        default_threshold_s: float = 90.0,
        grace_period_s: float = 4.0,
    ):
        """thresholds: limiar por zona (sobrescreve o default)."""
        self.thresholds = thresholds or {}
        self.default_threshold_s = default_threshold_s
        self.grace_period_s = grace_period_s
        self._state: dict[tuple[str, int], _Presence] = {}

    def threshold(self, zone: str) -> float:
        return self.thresholds.get(zone, self.default_threshold_s)

    def update(self, zone_hits: dict[str, set[int]], now: float) -> list[LoiterHit]:
        """zone_hits: {zona: {track_ids presentes neste frame}}. Retorna só alertas NOVOS."""
        # 1) Expira quem está ausente há mais que o período de graça (antes de atualizar,
        #    para que uma reaparição após longa ausência comece um cronômetro novo).
        for key, p in list(self._state.items()):
            if now - p.last_seen > self.grace_period_s:
                del self._state[key]

        # 2) Registra/atualiza presenças deste frame.
        for zone, ids in zone_hits.items():
            for tid in ids:
                p = self._state.get((zone, tid))
                if p is None:
                    self._state[(zone, tid)] = _Presence(first_seen=now, last_seen=now)
                else:
                    p.last_seen = now

        hits: list[LoiterHit] = []
        for (zone, tid), p in self._state.items():
            if p.alerted:
                continue
            dwell = p.last_seen - p.first_seen
            if dwell >= self.threshold(zone):
                p.alerted = True
                hits.append(LoiterHit(zone=zone, track_id=tid, dwell_s=dwell))
        return hits

    def dwell(self, zone: str, track_id: int) -> float | None:
        p = self._state.get((zone, track_id))
        return None if p is None else p.last_seen - p.first_seen
