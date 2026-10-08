"""Identidade por track: votação de reconhecimento facial ao longo de vários frames.

Lógica pura (tempo injetado). Nunca decide com 1 frame:
- conhecido: `known_votes` observações do mesmo nome na janela recente;
- desconhecido: `unknown_votes` rostos de boa qualidade abaixo do limiar de
  "desconhecido" e NENHUM acerto na janela (zona cinzenta entre os limiares é ignorada);
- não identificado: presente há `unidentified_after_s` sem decisão (ex.: de costas).

Quando o tracker troca o ID de uma pessoa já identificada, o track novo que
surge no mesmo lugar herda a identidade (sem novo alerta).
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Literal

Box = tuple[int, int, int, int]
Status = Literal["pending", "known", "unknown"]
HitKind = Literal["known", "unknown", "unidentified"]


@dataclass(frozen=True)
class IdentityCfg:
    match_threshold: float = 0.45  # >= isso: é a pessoa da galeria
    unknown_threshold: float = 0.30  # < isso (rosto bom): voto de desconhecido
    known_votes: int = 3
    unknown_votes: int = 5
    window: int = 8  # últimas N observações consideradas
    sample_interval_s: float = 0.3  # enquanto pendente
    recheck_interval_s: float = 2.0  # depois de decidido (pega troca de ID)
    unidentified_after_s: float = 20.0
    forget_after_s: float = 3.0  # track sumido por mais que isso é encerrado
    inherit_window_s: float = 10.0
    inherit_iou: float = 0.3


@dataclass(frozen=True)
class IdentityHit:
    track_id: int
    kind: HitKind
    name: str | None
    similarity: float | None
    present_s: float


@dataclass
class TrackIdentity:
    track_id: int
    first_seen: float
    last_seen: float
    box: Box
    status: Status = "pending"
    name: str | None = None
    similarity: float | None = None
    last_sample: float = float("-inf")
    observations: deque = field(default_factory=deque)  # (name|None, sim)
    reported: set[str] = field(default_factory=set)
    flags: set[str] = field(default_factory=set)  # livre para o pipeline (ex.: "entrance")


def iou(a: Box, b: Box) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    area = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / area if area > 0 else 0.0


class IdentityTracker:
    def __init__(self, cfg: IdentityCfg | None = None):
        self.cfg = cfg or IdentityCfg()
        self.tracks: dict[int, TrackIdentity] = {}
        self._lost: list[TrackIdentity] = []

    # ---- presença -----------------------------------------------------
    def update(self, boxes: dict[int, Box], now: float) -> list[IdentityHit]:
        """Atualiza os tracks visíveis. Retorna alertas de "não identificado"."""
        for tid, box in boxes.items():
            t = self.tracks.get(tid)
            if t is None:
                t = self._inherit(tid, box, now) or TrackIdentity(tid, now, now, box)
                self.tracks[tid] = t
            t.last_seen, t.box = now, box

        for tid in [tid for tid, t in self.tracks.items() if tid not in boxes]:
            if now - self.tracks[tid].last_seen > self.cfg.forget_after_s:
                self._lost.append(self.tracks.pop(tid))
        self._lost = [t for t in self._lost if now - t.last_seen <= self.cfg.inherit_window_s]

        hits = []
        for t in self.tracks.values():
            present = now - t.first_seen
            if (
                t.status == "pending"
                and present >= self.cfg.unidentified_after_s
                and "unidentified" not in t.reported
            ):
                t.reported.add("unidentified")
                hits.append(IdentityHit(t.track_id, "unidentified", None, None, present))
        return hits

    def _inherit(self, tid: int, box: Box, now: float) -> TrackIdentity | None:
        """Track novo no lugar de um recém-perdido: provavelmente a mesma pessoa."""
        best = max(self._lost, key=lambda t: iou(t.box, box), default=None)
        if best is None or iou(best.box, box) < self.cfg.inherit_iou:
            return None
        self._lost.remove(best)
        best.track_id, best.box, best.last_seen = tid, box, now
        return best

    # ---- reconhecimento ----------------------------------------------
    def wants_face(self, track_id: int, now: float) -> bool:
        t = self.tracks.get(track_id)
        if t is None:
            return False
        interval = (
            self.cfg.sample_interval_s if t.status == "pending" else self.cfg.recheck_interval_s
        )
        return now - t.last_sample >= interval

    def mark_sampled(self, track_id: int, now: float) -> None:
        """Tentou ler o rosto e não havia rosto utilizável (conta para o intervalo)."""
        if t := self.tracks.get(track_id):
            t.last_sample = now

    def observe(
        self, track_id: int, name: str | None, similarity: float, now: float
    ) -> IdentityHit | None:
        """Registra uma leitura de rosto de boa qualidade. Retorna a decisão, se mudou."""
        t = self.tracks.get(track_id)
        if t is None:
            return None
        t.last_sample = now
        cfg = self.cfg
        if name is not None and similarity >= cfg.match_threshold:
            t.observations.append((name, similarity))
        elif similarity < cfg.unknown_threshold:
            t.observations.append((None, similarity))
        else:
            return None  # zona cinzenta: não vota
        while len(t.observations) > cfg.window:
            t.observations.popleft()

        names = Counter(n for n, _ in t.observations if n is not None)
        unknown = sum(1 for n, _ in t.observations if n is None)
        best, best_n = names.most_common(1)[0] if names else (None, 0)

        if best_n >= cfg.known_votes and (t.status != "known" or t.name != best):
            t.status, t.name = "known", best
            t.similarity = max(s for n, s in t.observations if n == best)
            return self._hit(t, "known", now)
        if unknown >= cfg.unknown_votes and best_n == 0 and t.status != "unknown":
            t.status, t.name = "unknown", None
            t.similarity = max(s for _, s in t.observations)
            return self._hit(t, "unknown", now)
        return None

    def _hit(self, t: TrackIdentity, kind: HitKind, now: float) -> IdentityHit:
        t.reported.add(kind)
        return IdentityHit(t.track_id, kind, t.name, t.similarity, now - t.first_seen)

    # ---- consulta -----------------------------------------------------
    def get(self, track_id: int) -> TrackIdentity | None:
        return self.tracks.get(track_id)
