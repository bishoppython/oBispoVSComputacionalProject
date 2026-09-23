"""Loop principal: fonte -> detecção -> regras -> eventos."""

from __future__ import annotations

import logging
import time

import cv2

from vigia.config import AppConfig, Secrets
from vigia.detection.detector import Detection, Detector
from vigia.events.engine import EventEngine, EventSink
from vigia.events.models import Event
from vigia.events.sinks import LogSink, SnapshotSink
from vigia.notify.telegram import TelegramClient, TelegramNotifier
from vigia.rules.loitering import LoiteringTracker
from vigia.rules.occupancy import OccupancyTracker
from vigia.rules.zones import load_zones
from vigia.video.source import VideoSource, resize_to_width
from vigia.viz.overlay import draw_detections, draw_hud, draw_zones

log = logging.getLogger(__name__)
WINDOW = "vigia"


class Pipeline:
    def __init__(self, cfg: AppConfig, secrets: Secrets):
        self.cfg = cfg
        self.source = VideoSource(cfg.camera.source, cfg.camera.id, cfg.camera.reconnect_seconds)
        self.detector = Detector(cfg.detector)
        self.zones = load_zones(cfg.zones_file)
        self.loiter_zones = [z for z in self.zones if z.kind == "loitering"]
        thresholds = {z.name: z.threshold_s for z in self.loiter_zones if z.threshold_s}
        self.loitering = LoiteringTracker(
            thresholds=thresholds,
            default_threshold_s=cfg.loitering.default_threshold_s,
            grace_period_s=cfg.loitering.grace_period_s,
        )
        self.occupancy = (
            OccupancyTracker(
                thresholds=thresholds,
                default_threshold_s=cfg.loitering.default_threshold_s,
                grace_period_s=cfg.loitering.grace_period_s,
            )
            if cfg.loitering.occupancy_fallback
            else None
        )
        self.engine = EventEngine(self._build_sinks(secrets), cfg.events.cooldown_s)
        if not self.zones:
            log.warning("Nenhuma zona em %s — rode `vigia zones` para criar.", cfg.zones_file)

    def _build_sinks(self, secrets: Secrets) -> list[EventSink]:
        sinks: list[EventSink] = [LogSink(), SnapshotSink(self.cfg.events.snapshot_dir)]
        if self.cfg.telegram.enabled:
            if secrets.telegram_ready:
                client = TelegramClient(secrets.telegram_bot_token, secrets.telegram_chat_id)
                sinks.append(TelegramNotifier(client))
            else:
                log.warning("Telegram habilitado, mas TELEGRAM_BOT_TOKEN/CHAT_ID ausentes no .env")
        return sinks

    # ------------------------------------------------------------------
    def _loitering_step(self, frame, dets: list[Detection], now: float) -> None:
        h, w = frame.shape[:2]
        people = [d for d in dets if d.cls_name == "person" and d.track_id is not None]
        hits = {
            z.name: {d.track_id for d in people if z.contains(d.anchor, w, h)}
            for z in self.loiter_zones
        }
        for hit in self.loitering.update(hits, now):
            det = next((d for d in people if d.track_id == hit.track_id), None)
            snap = draw_zones(frame.copy(), self.zones)
            snap = draw_detections(snap, dets, highlight={hit.track_id})
            self.engine.emit(
                Event(
                    kind="loitering",
                    camera_id=self.cfg.camera.id,
                    zone=hit.zone,
                    track_id=hit.track_id,
                    bbox=det.xyxy if det else None,
                    severity="alerta",
                    message=f"Pessoa parada há {hit.dwell_s:.0f}s na zona '{hit.zone}'.",
                    frame=snap,
                    meta={"dwell_s": hit.dwell_s},
                )
            )

    def _occupancy_step(self, frame, dets: list[Detection], now: float) -> None:
        """Fallback da permanência: conta pessoas na zona, com ou sem track_id.

        Emite com kind="loitering" de propósito: a chave de cooldown é a mesma do
        alerta por track, então a mesma situação nunca gera dois alertas.
        """
        if self.occupancy is None:
            return
        h, w = frame.shape[:2]
        people = [d for d in dets if d.cls_name == "person"]
        inside = {
            z.name: [d for d in people if z.contains(d.anchor, w, h)] for z in self.loiter_zones
        }
        counts = {name: len(ds) for name, ds in inside.items()}
        for hit in self.occupancy.update(counts, now):
            in_zone = inside.get(hit.zone, [])
            snap = draw_zones(frame.copy(), self.zones)
            snap = draw_detections(
                snap, dets, highlight={d.track_id for d in in_zone if d.track_id is not None}
            )
            self.engine.emit(
                Event(
                    kind="loitering",
                    camera_id=self.cfg.camera.id,
                    zone=hit.zone,
                    bbox=in_zone[0].xyxy if in_zone else None,
                    severity="alerta",
                    message=f"Zona '{hit.zone}' ocupada continuamente há {hit.occupied_s:.0f}s.",
                    frame=snap,
                    meta={"occupied_s": hit.occupied_s, "source": "occupancy"},
                )
            )

    def _dwell_labels(self, dets: list[Detection]) -> dict[int, str]:
        labels: dict[int, str] = {}
        for d in dets:
            if d.track_id is None:
                continue
            for z in self.loiter_zones:
                t = self.loitering.dwell(z.name, d.track_id)
                if t is not None:
                    labels[d.track_id] = f"{t:.0f}s/{self.loitering.threshold(z.name):.0f}s"
        return labels

    # ------------------------------------------------------------------
    def run(self) -> None:
        show = self.cfg.display.show_window
        self.source.start()
        fps, last = 0.0, time.monotonic()
        log.info("Pipeline iniciado (q para sair).")
        try:
            while True:
                ok, frame, ts = self.source.read()
                if not ok:
                    if self.source.ended:
                        break
                    continue
                frame = resize_to_width(frame, self.cfg.camera.width)
                dets = self.detector.track(frame)

                self._loitering_step(frame, dets, ts)
                self._occupancy_step(frame, dets, ts)
                # fase 2: self._face_step(...)   fase 3: self._door_step / _vehicle_step

                now = time.monotonic()
                fps = 0.9 * fps + 0.1 * (1.0 / max(now - last, 1e-6))
                last = now

                if show:
                    view = draw_zones(frame, self.zones)
                    view = draw_detections(view, dets, labels=self._dwell_labels(dets))
                    cv2.imshow(WINDOW, draw_hud(view, fps, self.cfg.camera.id))
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
        except KeyboardInterrupt:
            log.info("Interrompido pelo usuário.")
        finally:
            self.source.stop()
            self.engine.close()
            if show:
                cv2.destroyAllWindows()
