"""Regra de ocupação de zona: quanto tempo a zona fica ocupada por QUALQUER pessoa.

Fallback do `LoiteringTracker`: se o tracker trocar o ID da mesma pessoa, o cronômetro
por track zera, mas a zona continua ocupada. Aqui não importa quem está na zona,
só que haja alguém. Lógica pura e com tempo injetado.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _Occupancy:
    since: float
    last_seen: float
    alerted: bool = False


@dataclass(frozen=True)
class OccupancyHit:
    zone: str
    occupied_s: float


class OccupancyTracker:
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
        self._state: dict[str, _Occupancy] = {}

    def threshold(self, zone: str) -> float:
        return self.thresholds.get(zone, self.default_threshold_s)

    def update(self, zone_counts: dict[str, int], now: float) -> list[OccupancyHit]:
        """zone_counts: {zona: nº de pessoas neste frame}. Retorna só alertas NOVOS.

        Um alerta por episódio de ocupação contínua; a zona precisa ficar vazia por
        mais que o período de graça para que um novo episódio comece.
        """
        # 1) Encerra episódios de zonas vazias há mais que o período de graça.
        for zone, occ in list(self._state.items()):
            if now - occ.last_seen > self.grace_period_s:
                del self._state[zone]

        # 2) Registra/atualiza zonas ocupadas neste frame.
        for zone, count in zone_counts.items():
            if count <= 0:
                continue
            occ = self._state.get(zone)
            if occ is None:
                self._state[zone] = _Occupancy(since=now, last_seen=now)
            else:
                occ.last_seen = now

        hits: list[OccupancyHit] = []
        for zone, occ in self._state.items():
            if occ.alerted:
                continue
            occupied = occ.last_seen - occ.since
            if occupied >= self.threshold(zone):
                occ.alerted = True
                hits.append(OccupancyHit(zone=zone, occupied_s=occupied))
        return hits

    def occupied_for(self, zone: str) -> float | None:
        occ = self._state.get(zone)
        return None if occ is None else occ.last_seen - occ.since
