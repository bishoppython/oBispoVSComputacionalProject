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
from vigia.notify.hub import HubClient, HubSink, Outbox
from vigia.notify.telegram import TelegramClient, TelegramNotifier
from vigia.rules.loitering import LoiteringTracker
from vigia.rules.occupancy import OccupancyTracker
from vigia.rules.zones import load_zones
from vigia.video.publisher import LivePublisher
from vigia.video.source import VideoSource, resize_to_width
from vigia.viz.overlay import draw_detections, draw_hud, draw_zones

log = logging.getLogger(__name__)
WINDOW = "vigia"
CAMERA_STALE_S = 10.0  # sem frame novo por mais que isso -> câmera sem sinal


class Pipeline:
    def __init__(self, cfg: AppConfig, secrets: Secrets):
        self.cfg = cfg
        self._fps = 0.0
        self._last_frame_at = 0.0
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
        self.engine = EventEngine(
            self._build_sinks(secrets),
            cfg.events.cooldown_s,
            cooldown_by_kind=cfg.events.cooldown_by_kind,
        )
        self.faces, self.face_sync = self._build_faces(secrets)
        self.live = (
            LivePublisher(secrets.vigia_live_url, cfg.live.fps, cfg.live.encoder, cfg.live.bitrate)
            if cfg.live.enabled and secrets.vigia_live_url
            else None
        )
        if cfg.live.enabled and not secrets.vigia_live_url:
            log.warning("Vídeo ao vivo habilitado, mas VIGIA_LIVE_URL ausente no .env")
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
        if self.cfg.hub.enabled:
            if secrets.vigia_hub_token:
                hub = self.cfg.hub
                client = HubClient(hub.url, secrets.vigia_hub_token, hub.timeout_s)
                sinks.append(
                    HubSink(
                        client,
                        Outbox(hub.outbox_dir),
                        heartbeat_s=hub.heartbeat_s,
                        retry_s=hub.retry_s,
                        status_fn=self.status,
                    )
                )
            else:
                log.warning("Hub habilitado, mas VIGIA_HUB_TOKEN ausente no .env")
        return sinks

    def _build_faces(self, secrets: Secrets):
        """Reconhecimento facial: precisa do hub (é de lá que vem a galeria)."""
        if not self.cfg.face.enabled:
            return None, None
        if not (self.cfg.hub.enabled and secrets.vigia_hub_token):
            log.warning("Reconhecimento facial precisa do hub (hub.enabled + VIGIA_HUB_TOKEN).")
            return None, None
        from vigia.face.encoder import InsightFaceEncoder
        from vigia.face.quality import QualityCfg
        from vigia.face.sync import GallerySync
        from vigia.face.watcher import FaceWatcher
        from vigia.rules.identity import IdentityCfg, IdentityTracker

        fc = self.cfg.face
        encoder = InsightFaceEncoder(
            fc.model,
            fc.det_size,
            fc.device,
            QualityCfg(min_face_px=fc.min_face_px, min_frontal=fc.min_frontal),
        )
        identity = IdentityTracker(
            IdentityCfg(
                match_threshold=fc.match_threshold,
                unknown_threshold=fc.unknown_threshold,
                known_votes=fc.known_votes,
                unknown_votes=fc.unknown_votes,
                unidentified_after_s=fc.unidentified_after_s,
            )
        )
        watcher = FaceWatcher(fc, self.cfg.camera.id, self.zones, encoder, identity)
        hub = HubClient(self.cfg.hub.url, secrets.vigia_hub_token, self.cfg.hub.timeout_s)
        sync = GallerySync(hub, encoder, fc.cache_path, watcher.set_gallery, fc.sync_interval_s)
        return watcher, sync

    def _face_step(self, frame, dets: list[Detection], now: float) -> None:
        if self.faces is None:
            return
        for event in self.faces.step(frame, dets, now):
            labels, colors, highlight = self.faces.overlay(dets)
            highlight = highlight | ({event.track_id} if event.severity != "info" else set())
            snap = draw_zones(frame.copy(), self.zones)
            event.frame = draw_detections(snap, dets, labels, highlight, colors)
            self.engine.emit(event)

    def status(self) -> dict:
        """Estado enviado no heartbeat ao hub."""
        age = time.monotonic() - self._last_frame_at
        return {
            "camera_id": self.cfg.camera.id,
            "camera_ok": self._last_frame_at > 0 and age < CAMERA_STALE_S,
            "fps": round(self._fps, 1),
        }

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

    def _annotate(self, frame, dets: list[Detection]):
        """Frame com zonas, caixas, cronômetros e identidades (janela e vídeo ao vivo)."""
        labels = self._dwell_labels(dets)
        colors: dict = {}
        highlight: set = set()
        if self.faces is not None:
            face_labels, colors, highlight = self.faces.overlay(dets)
            for tid, text in face_labels.items():
                labels[tid] = f"{text} {labels[tid]}" if tid in labels else text
        view = draw_zones(frame.copy(), self.zones)
        return draw_detections(view, dets, labels, highlight, colors)

    # ------------------------------------------------------------------
    def run(self) -> None:
        show = self.cfg.display.show_window
        self.source.start()
        if self.face_sync:
            self.face_sync.start()
        if self.live:
            self.live.start()
        last = time.monotonic()
        log.info("Pipeline iniciado (q para sair).")
        try:
            while True:
                ok, frame, ts = self.source.read()
                if not ok:
                    if self.source.ended:
                        break
                    continue
                self._last_frame_at = time.monotonic()
                frame = resize_to_width(frame, self.cfg.camera.width)
                dets = self.detector.track(frame)

                self._loitering_step(frame, dets, ts)
                self._occupancy_step(frame, dets, ts)
                self._face_step(frame, dets, ts)
                # fase 3: self._door_step / _vehicle_step

                now = time.monotonic()
                self._fps = 0.9 * self._fps + 0.1 * (1.0 / max(now - last, 1e-6))
                last = now

                if show or self.live:
                    view = draw_hud(self._annotate(frame, dets), self._fps, self.cfg.camera.id)
                    if self.live:
                        self.live.publish(view)
                    if show:
                        cv2.imshow(WINDOW, view)
                        if cv2.waitKey(1) & 0xFF == ord("q"):
                            break
        except KeyboardInterrupt:
            log.info("Interrompido pelo usuário.")
        finally:
            if self.face_sync:
                self.face_sync.stop()
            if self.live:
                self.live.stop()
            self.source.stop()
            self.engine.close()
            if show:
                cv2.destroyAllWindows()
