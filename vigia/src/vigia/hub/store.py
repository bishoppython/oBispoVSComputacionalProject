"""Histórico de eventos do hub: SQLite + fotos em disco, organizadas por mês."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from vigia.events.models import Event

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    timestamp REAL NOT NULL,
    camera_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    zone TEXT,
    track_id INTEGER,
    message TEXT NOT NULL,
    meta TEXT NOT NULL,
    photo TEXT,
    received_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS events_ts ON events (timestamp);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""
COLUMNS = "id, timestamp, camera_id, kind, severity, zone, track_id, message, meta, photo"


@dataclass
class StoredEvent:
    id: str
    timestamp: float
    camera_id: str
    kind: str
    severity: str
    zone: str | None
    track_id: int | None
    message: str
    meta: dict = field(default_factory=dict)
    photo: str | None = None  # caminho relativo a data_dir

    def to_event(self) -> Event:
        return Event(
            kind=self.kind,
            camera_id=self.camera_id,
            message=self.message,
            severity=self.severity,  # type: ignore[arg-type]
            zone=self.zone,
            track_id=self.track_id,
            timestamp=self.timestamp,
            meta=self.meta,
        )


class EventStore:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.data_dir / "vigia.db", check_same_thread=False)
        self._db.executescript(SCHEMA)

    def add(self, payload: dict, jpeg: bytes | None, received_at: float) -> StoredEvent | None:
        """Grava o evento. Retorna None se o `id` já existia (reenvio da outbox)."""
        ev = StoredEvent(
            id=payload["id"],
            timestamp=float(payload["timestamp"]),
            camera_id=payload["camera_id"],
            kind=payload["kind"],
            severity=payload["severity"],
            zone=payload.get("zone"),
            track_id=payload.get("track_id"),
            message=payload["message"],
            meta=payload.get("meta") or {},
        )
        if jpeg:
            month = datetime.fromtimestamp(ev.timestamp).strftime("%Y-%m")
            stamp = datetime.fromtimestamp(ev.timestamp).strftime("%Y%m%d_%H%M%S")
            ev.photo = f"photos/{month}/{stamp}_{ev.id}.jpg"
        with self._lock:
            cur = self._db.execute(
                f"INSERT OR IGNORE INTO events ({COLUMNS}, received_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ev.id,
                    ev.timestamp,
                    ev.camera_id,
                    ev.kind,
                    ev.severity,
                    ev.zone,
                    ev.track_id,
                    ev.message,
                    json.dumps(ev.meta),
                    ev.photo,
                    received_at,
                ),
            )
            self._db.commit()
            if cur.rowcount == 0:
                return None
        if jpeg and ev.photo:
            path = self.data_dir / ev.photo
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(jpeg)
        return ev

    def read_photo(self, ev: StoredEvent) -> bytes | None:
        if not ev.photo:
            return None
        path = self.data_dir / ev.photo
        return path.read_bytes() if path.exists() else None

    def between(self, start_ts: float, end_ts: float) -> list[StoredEvent]:
        with self._lock:
            rows = self._db.execute(
                f"SELECT {COLUMNS} FROM events WHERE timestamp >= ? AND timestamp < ? "
                "ORDER BY timestamp",
                (start_ts, end_ts),
            ).fetchall()
        return [_row(r) for r in rows]

    def count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def purge_before(self, ts: float) -> int:
        """Apaga eventos (e fotos) anteriores a `ts`. Retorna quantos foram apagados."""
        old = self.between(0.0, ts)
        for ev in old:
            if ev.photo:
                (self.data_dir / ev.photo).unlink(missing_ok=True)
        with self._lock:
            self._db.execute("DELETE FROM events WHERE timestamp < ?", (ts,))
            self._db.commit()
        return len(old)

    def get_state(self, key: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_state(self, key: str, value: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO state (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()


def _row(r: tuple) -> StoredEvent:
    return StoredEvent(
        id=r[0],
        timestamp=r[1],
        camera_id=r[2],
        kind=r[3],
        severity=r[4],
        zone=r[5],
        track_id=r[6],
        message=r[7],
        meta=json.loads(r[8]),
        photo=r[9],
    )
