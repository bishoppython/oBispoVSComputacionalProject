"""Motor de eventos: aplica cooldown e distribui para os sinks (Telegram, disco, log)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Protocol

from vigia.events.models import Event

log = logging.getLogger(__name__)


class EventSink(Protocol):
    def handle(self, event: Event) -> None: ...
    def close(self) -> None: ...


class EventEngine:
    def __init__(
        self,
        sinks: list[EventSink],
        cooldown_s: float = 120.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.sinks = sinks
        self.cooldown_s = cooldown_s
        self._clock = clock
        self._last_sent: dict[str, float] = {}

    def emit(self, event: Event) -> bool:
        """Retorna True se o evento foi despachado, False se caiu no cooldown."""
        now = self._clock()
        last = self._last_sent.get(event.dedup_key)
        if last is not None and now - last < self.cooldown_s:
            log.debug("Evento suprimido (cooldown): %s", event.dedup_key)
            return False
        self._last_sent[event.dedup_key] = now
        for sink in self.sinks:
            try:
                sink.handle(event)
            except Exception:  # um sink quebrado não pode derrubar o pipeline
                log.exception("Falha no sink %s", type(sink).__name__)
        return True

    def close(self) -> None:
        for sink in self.sinks:
            try:
                sink.close()
            except Exception:
                log.exception("Falha ao fechar sink %s", type(sink).__name__)
