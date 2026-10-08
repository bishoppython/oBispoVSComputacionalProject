"""Orquestração do hub: grava eventos, despacha para os canais e roda as rotinas."""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import httpx

from vigia.hub.channels import Channel, EvolutionClient, TelegramChannel, WhatsAppChannel
from vigia.hub.monitor import PresenceMonitor
from vigia.hub.report import (
    build_report_pdf,
    month_bounds,
    previous_month,
    report_caption,
    summarize,
)
from vigia.hub.settings import HubSettings
from vigia.hub.store import EventStore, StoredEvent
from vigia.notify.telegram import TelegramClient

log = logging.getLogger(__name__)
TICK_S = 30.0
DAY_S = 86400.0


@dataclass
class _Job:
    kind: str  # "alert" | "text" | "document"
    event: StoredEvent | None = None
    photo: bytes | None = None
    text: str = ""
    content: bytes = b""
    filename: str = ""


class Hub:
    def __init__(
        self,
        settings: HubSettings,
        store: EventStore,
        channels: list[Channel],
        camera_probe: Callable[[], bool] | None = None,
        clock: Callable[[], float] = time.time,
        retries: int = 3,
    ):
        self.settings = settings
        self.store = store
        self.channels = channels
        self.camera_probe = camera_probe
        self._clock = clock
        self.retries = retries
        now = clock()
        self.node = PresenceMonitor(settings.hub_node_offline_after_s, now)
        self.camera = PresenceMonitor(settings.hub_camera_offline_after_s, now)
        self.node_status: dict = {}
        self._jobs: queue.Queue[_Job | None] = queue.Queue(maxsize=500)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        # Na primeira execução não manda o relatório do mês anterior (ainda não havia dados).
        if store.get_state("last_report") is None:
            y, m = previous_month(datetime.fromtimestamp(now).date())
            store.set_state("last_report", f"{y}-{m:02d}")

    # ---- entrada -------------------------------------------------------
    def ingest(self, payload: dict, photo: bytes | None) -> bool:
        """Grava e agenda o alerta. False se for duplicado (reenvio da outbox)."""
        ev = self.store.add(payload, photo, received_at=self._clock())
        if ev is None:
            return False
        log.warning("Alerta recebido: [%s] %s", ev.kind, ev.message)
        self._enqueue(_Job("alert", event=ev, photo=photo))
        return True

    def heartbeat(self, status: dict) -> None:
        now = self._clock()
        self.node_status = {**status, "received_at": now}
        if self.node.beat(now) == "online":
            node = status.get("node", "nó de inferência")
            log.info("Nó %s voltou.", node)
            self._notify_node(f"▶️ Vigilância retomada: {node} voltou a analisar a câmera.")

    def notify_text(self, text: str) -> None:
        self._enqueue(_Job("text", text=text))

    # ---- rotinas periódicas -------------------------------------------
    def tick(self) -> None:
        now = self._clock()
        if self.node.check(now) == "offline":
            since = datetime.fromtimestamp(self.node.last_signal).strftime("%d/%m %H:%M")
            log.warning("Nó de inferência sem heartbeat desde %s.", since)
            self._notify_node(
                f"⏸️ Vigilância pausada: o nó de inferência está sem contato desde {since}. "
                "A câmera continua no homelab, mas nenhum alerta será gerado."
            )
        self._check_camera(now)
        self._maybe_monthly_report(now)
        self._maybe_purge(now)

    def _check_camera(self, now: float) -> None:
        if self.camera_probe is None:
            return
        path = self.settings.hub_camera_path
        if self.camera_probe():
            if self.camera.beat(now) == "online":
                self.notify_text(f"📷 Câmera '{path}' voltou a transmitir.")
        elif self.camera.check(now) == "offline":
            since = datetime.fromtimestamp(self.camera.last_signal).strftime("%d/%m %H:%M")
            self.notify_text(
                f"📷❌ Câmera '{path}' sem sinal no homelab desde {since}. Verifique o cabo USB."
            )

    def _maybe_monthly_report(self, now: float) -> None:
        dt = datetime.fromtimestamp(now)
        due = dt.day > self.settings.hub_report_day or (
            dt.day == self.settings.hub_report_day and dt.hour >= self.settings.hub_report_hour
        )
        y, m = previous_month(dt.date())
        key = f"{y}-{m:02d}"
        if due and self.store.get_state("last_report") != key:
            self.send_monthly_report(y, m)
            self.store.set_state("last_report", key)

    def _maybe_purge(self, now: float) -> None:
        today = datetime.fromtimestamp(now).date().isoformat()
        if self.store.get_state("last_purge") == today:
            return
        n = self.store.purge_before(now - self.settings.hub_retention_days * DAY_S)
        self.store.set_state("last_purge", today)
        if n:
            log.info("Retenção: %d evento(s) antigo(s) apagado(s).", n)

    def send_monthly_report(self, year: int, month: int) -> dict:
        events = self.store.between(*month_bounds(year, month))
        summary = summarize(events)
        pdf = build_report_pdf(events, year, month, self.store.read_photo)
        filename = f"vigia_relatorio_{year}-{month:02d}.pdf"
        self._enqueue(
            _Job(
                "document",
                content=pdf,
                filename=filename,
                text=report_caption(summary, year, month),
            )
        )
        log.info("Relatório %s: %d alerta(s), %d KB.", filename, summary.total, len(pdf) // 1024)
        return {"month": f"{year}-{month:02d}", "alerts": summary.total, "bytes": len(pdf)}

    # ---- despacho -----------------------------------------------------
    def _notify_node(self, text: str) -> None:
        if self.settings.hub_notify_node_status:
            self.notify_text(text)

    def _enqueue(self, job: _Job) -> None:
        try:
            self._jobs.put_nowait(job)
        except queue.Full:
            log.error("Fila de envio cheia; descartando %s", job.kind)

    def _send(self, channel: Channel, job: _Job) -> None:
        if job.kind == "alert" and job.event is not None:
            channel.send_alert(job.event.to_event(), job.photo)
        elif job.kind == "text":
            channel.send_text(job.text)
        elif job.kind == "document":
            channel.send_document(job.content, job.filename, job.text)

    def process_pending(self, sleep: Callable[[float], None] = time.sleep) -> None:
        """Envia tudo o que está na fila (o worker chama em loop; os testes, direto)."""
        while True:
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                return
            if job is None:
                return
            self._deliver(job, sleep)

    def _deliver(self, job: _Job, sleep: Callable[[float], None]) -> None:
        for channel in self.channels:  # um canal fora do ar não atrasa nem bloqueia o outro
            for attempt in range(1, self.retries + 1):
                try:
                    self._send(channel, job)
                    break
                except Exception as exc:
                    log.warning(
                        "%s falhou (%s, tentativa %d/%d): %s",
                        channel.name, job.kind, attempt, self.retries, exc,
                    )  # fmt: skip
                    if attempt < self.retries:
                        sleep(3 * attempt)

    # ---- ciclo de vida ------------------------------------------------
    def start(self) -> None:
        self._threads = [
            threading.Thread(target=self._send_loop, name="hub-send", daemon=True),
            threading.Thread(target=self._tick_loop, name="hub-tick", daemon=True),
        ]
        for t in self._threads:
            t.start()
        names = ", ".join(c.name for c in self.channels) or "nenhum"
        log.info("Hub iniciado. Canais: %s.", names)

    def _send_loop(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            self._deliver(job, time.sleep)

    def _tick_loop(self) -> None:
        while not self._stop.wait(TICK_S):
            try:
                self.tick()
            except Exception:
                log.exception("Falha na rotina periódica do hub")

    def stop(self) -> None:
        self._stop.set()
        self._jobs.put(None)
        for t in self._threads:
            t.join(timeout=10)
        for c in self.channels:
            c.close()
        self.store.close()


def mediamtx_probe(api_url: str, path: str) -> Callable[[], bool]:
    """Pergunta ao mediamtx se o caminho da câmera está recebendo vídeo."""
    url = f"{api_url.rstrip('/')}/v3/paths/get/{path}"

    def probe() -> bool:
        try:
            r = httpx.get(url, timeout=5.0)
            return r.status_code == 200 and bool(r.json().get("ready"))
        except (httpx.HTTPError, ValueError):
            return False

    return probe


def build_hub(settings: HubSettings) -> Hub:
    channels: list[Channel] = []
    if settings.telegram_ready:
        channels.append(
            TelegramChannel(TelegramClient(settings.telegram_bot_token, settings.telegram_chat_id))
        )
    else:
        log.warning("Telegram desativado: TELEGRAM_BOT_TOKEN/CHAT_ID ausentes.")
    if settings.whatsapp_ready:
        evo = EvolutionClient(
            settings.evolution_url,
            settings.evolution_api_key,
            settings.evolution_instance,
            settings.whatsapp_to,
        )
        channels.append(WhatsAppChannel(evo))
    else:
        log.warning("WhatsApp desativado: EVOLUTION_*/WHATSAPP_TO incompletos.")
    probe = (
        mediamtx_probe(settings.hub_mediamtx_api, settings.hub_camera_path)
        if settings.hub_mediamtx_api
        else None
    )
    return Hub(settings, EventStore(settings.hub_data_dir), channels, camera_probe=probe)
