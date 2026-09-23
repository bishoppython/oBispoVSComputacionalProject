"""Sinks simples: log no terminal e snapshot em disco."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import cv2

from vigia.events.models import SEVERITY_ICON, Event

log = logging.getLogger("vigia.events")


class LogSink:
    def handle(self, event: Event) -> None:
        log.warning("%s [%s] %s", SEVERITY_ICON[event.severity], event.kind, event.message)

    def close(self) -> None:
        pass


class SnapshotSink:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def handle(self, event: Event) -> None:
        if event.frame is None:
            return
        stamp = datetime.fromtimestamp(event.timestamp).strftime("%Y%m%d_%H%M%S")
        name = f"{stamp}_{event.camera_id}_{event.kind}_{event.zone or 'na'}.jpg"
        path = self.directory / name
        cv2.imwrite(str(path), event.frame)
        event.meta["snapshot_path"] = str(path)

    def close(self) -> None:
        pass
