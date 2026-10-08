"""Etapa de reconhecimento facial do pipeline: detecções -> identidades -> eventos.

- Pessoa conhecida: evento informativo ("Ana entrou no quarto"), sem alarme.
- Rosto desconhecido confirmado: alerta crítico + alarme sonoro.
- Desconhecido na zona sensível (ex.: cama): alerta crítico próprio + alarme.
- Sem rosto reconhecível por muito tempo: alerta leve, sem alarme.
"""

from __future__ import annotations

import logging
from typing import Protocol

import numpy as np

from vigia.config import FaceCfg
from vigia.detection.detector import Detection
from vigia.events.models import Event
from vigia.face.contracts import FaceObservation
from vigia.face.gallery import MemoryGallery
from vigia.rules.identity import IdentityHit, IdentityTracker
from vigia.rules.zones import Zone

log = logging.getLogger(__name__)

KNOWN_COLOR = (60, 220, 60)
PENDING_COLOR = (0, 220, 255)


class Encoder(Protocol):
    def encode(
        self, frame: np.ndarray, person_box: tuple[int, int, int, int]
    ) -> list[FaceObservation]: ...


class FaceWatcher:
    def __init__(
        self,
        cfg: FaceCfg,
        camera_id: str,
        zones: list[Zone],
        encoder: Encoder,
        identity: IdentityTracker,
    ):
        self.cfg = cfg
        self.camera_id = camera_id
        self.entrances = [z for z in zones if z.kind == "entrance"]
        self.sensitive = [z for z in zones if z.kind == "sensitive"]
        self.encoder = encoder
        self.identity = identity
        self.gallery = MemoryGallery()
        self._warned_empty = False

    def set_gallery(self, gallery: MemoryGallery) -> None:
        self.gallery = gallery  # troca atômica: chamado pela thread de sincronização
        self._warned_empty = False

    def step(self, frame: np.ndarray, dets: list[Detection], now: float) -> list[Event]:
        gallery = self.gallery
        if len(gallery) == 0:
            if not self._warned_empty:
                log.warning("Galeria vazia: cadastre rostos no painel. Reconhecimento pausado.")
                self._warned_empty = True
            return []

        h, w = frame.shape[:2]
        people = {d.track_id: d for d in dets if d.cls_name == "person" and d.track_id is not None}
        hits: list[IdentityHit] = self.identity.update(
            {tid: d.xyxy for tid, d in people.items()}, now
        )

        for tid, d in people.items():
            track = self.identity.get(tid)
            if track is not None and any(z.contains(d.anchor, w, h) for z in self.entrances):
                track.flags.add("entrance")
            if not self.identity.wants_face(tid, now):
                continue
            faces = self.encoder.encode(frame, d.xyxy)
            if not faces:
                self.identity.mark_sampled(tid, now)
                continue
            name, sim = gallery.best(faces[0].embedding)
            if hit := self.identity.observe(tid, name, sim, now):
                hits.append(hit)

        events = [self._event(hit, people.get(hit.track_id), w, h) for hit in hits]
        events += self._sensitive_events(people, w, h)
        return events

    def _zone_of(self, zones: list[Zone], d: Detection | None, w: int, h: int) -> Zone | None:
        if d is None:
            return None
        return next((z for z in zones if z.contains(d.anchor, w, h)), None)

    def _event(self, hit: IdentityHit, d: Detection | None, w: int, h: int) -> Event:
        bbox = d.xyxy if d else None
        meta = {"similarity": round(hit.similarity, 3) if hit.similarity is not None else None}
        if hit.kind == "known":
            track = self.identity.get(hit.track_id)
            entered = track is not None and "entrance" in track.flags
            verb = "entrou no quarto" if entered else "foi identificado(a) no quarto"
            return Event(
                kind="face_known",
                camera_id=self.camera_id,
                message=f"{hit.name} {verb}.",
                severity="info",
                subject=hit.name,
                track_id=hit.track_id,
                bbox=bbox,
                meta=meta,
            )
        if hit.kind == "unknown":
            zone = self._zone_of(self.sensitive, d, w, h)
            where = f" na zona '{zone.name}'" if zone else " no quarto"
            if zone and (track := self.identity.get(hit.track_id)):
                track.reported.add("sensitive")  # já avisado junto
            return Event(
                kind="face_unknown",
                camera_id=self.camera_id,
                message=f"Pessoa DESCONHECIDA{where}.",
                severity="critico",
                zone=zone.name if zone else None,
                track_id=hit.track_id,
                bbox=bbox,
                meta=meta | {"alarm": self.cfg.alarm_on_unknown},
            )
        return Event(
            kind="unidentified",
            camera_id=self.camera_id,
            message=f"Pessoa sem rosto reconhecível há {hit.present_s:.0f}s no quarto.",
            severity="alerta",
            track_id=hit.track_id,
            bbox=bbox,
            meta={"present_s": round(hit.present_s, 1)},
        )

    def _sensitive_events(self, people: dict[int, Detection], w: int, h: int) -> list[Event]:
        """Desconhecido que ENTRA na zona sensível depois de já ter sido detectado."""
        events = []
        for tid, d in people.items():
            track = self.identity.get(tid)
            if track is None or track.status != "unknown" or "sensitive" in track.reported:
                continue
            zone = self._zone_of(self.sensitive, d, w, h)
            if zone is None:
                continue
            track.reported.add("sensitive")
            events.append(
                Event(
                    kind="sensitive_zone",
                    camera_id=self.camera_id,
                    message=f"Pessoa desconhecida entrou na zona '{zone.name}'.",
                    severity="critico",
                    zone=zone.name,
                    track_id=tid,
                    bbox=d.xyxy,
                    meta={"alarm": self.cfg.alarm_on_unknown},
                )
            )
        return events

    # ---- desenho ------------------------------------------------------
    def overlay(self, dets: list[Detection]) -> tuple[dict, dict, set]:
        """(rótulos, cores, destaques) para o overlay de cada track."""
        labels, colors, highlight = {}, {}, set()
        for d in dets:
            track = self.identity.get(d.track_id) if d.track_id is not None else None
            if track is None or d.cls_name != "person":
                continue
            if track.status == "known":
                labels[d.track_id] = f"{track.name} ({track.similarity:.2f})"
                colors[d.track_id] = KNOWN_COLOR
            elif track.status == "unknown":
                labels[d.track_id] = "DESCONHECIDO"
                highlight.add(d.track_id)
            else:
                labels[d.track_id] = "?"
                colors[d.track_id] = PENDING_COLOR
        return labels, colors, highlight
