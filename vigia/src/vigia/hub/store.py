"""Histórico de eventos do hub: SQLite + fotos em disco, organizadas por mês."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
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
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS face_photos (
    id TEXT PRIMARY KEY,
    person_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL
);
"""
MIGRATIONS = {"subject": "ALTER TABLE events ADD COLUMN subject TEXT"}
COLUMNS = (
    "id, timestamp, camera_id, kind, severity, zone, track_id, message, meta, photo, "
    "subject, received_at"
)
PHOTO_STATUSES = {"pending", "ok", "sem_rosto"}


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
    subject: str | None = None
    received_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "received_at": self.received_at,
            "camera_id": self.camera_id,
            "kind": self.kind,
            "severity": self.severity,
            "zone": self.zone,
            "subject": self.subject,
            "message": self.message,
            "meta": self.meta,
            "has_photo": self.photo is not None,
        }

    def to_event(self) -> Event:
        return Event(
            kind=self.kind,
            camera_id=self.camera_id,
            message=self.message,
            severity=self.severity,  # type: ignore[arg-type]
            zone=self.zone,
            track_id=self.track_id,
            subject=self.subject,
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
        cols = {r[1] for r in self._db.execute("PRAGMA table_info(events)")}
        for col, ddl in MIGRATIONS.items():
            if col not in cols:
                self._db.execute(ddl)
        self._db.commit()

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
            subject=payload.get("subject"),
            received_at=received_at,
        )
        if jpeg:
            month = datetime.fromtimestamp(ev.timestamp).strftime("%Y-%m")
            stamp = datetime.fromtimestamp(ev.timestamp).strftime("%Y%m%d_%H%M%S")
            ev.photo = f"photos/{month}/{stamp}_{ev.id}.jpg"
        with self._lock:
            cur = self._db.execute(
                f"INSERT OR IGNORE INTO events ({COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    ev.subject,
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

    def get(self, event_id: str) -> StoredEvent | None:
        with self._lock:
            row = self._db.execute(
                f"SELECT {COLUMNS} FROM events WHERE id = ?", (event_id,)
            ).fetchone()
        return _row(row) if row else None

    def recent(self, limit: int = 50, since_received: float | None = None) -> list[StoredEvent]:
        """Mais recentes primeiro. `since_received`: só o que chegou depois (polling)."""
        sql = f"SELECT {COLUMNS} FROM events"
        args: tuple = ()
        if since_received is not None:
            sql += " WHERE received_at > ?"
            args = (since_received,)
        sql += " ORDER BY received_at DESC LIMIT ?"
        with self._lock:
            rows = self._db.execute(sql, (*args, limit)).fetchall()
        return [_row(r) for r in rows]

    # ---- cadastro de rostos ----------------------------------------------
    def add_person(self, name: str) -> int:
        with self._lock:
            row = self._db.execute("SELECT id FROM people WHERE name = ?", (name,)).fetchone()
            if row:
                return row[0]
            cur = self._db.execute(
                "INSERT INTO people (name, created_at) VALUES (?, ?)", (name, time.time())
            )
            self._db.commit()
            return cur.lastrowid

    def people(self) -> list[dict]:
        with self._lock:
            people = self._db.execute("SELECT id, name FROM people ORDER BY name").fetchall()
            photos = self._db.execute(
                "SELECT id, person_id, source, status, created_at FROM face_photos "
                "ORDER BY created_at"
            ).fetchall()
        by_person: dict[int, list[dict]] = {}
        for pid, person_id, source, status, created in photos:
            by_person.setdefault(person_id, []).append(
                {"id": pid, "source": source, "status": status, "created_at": created}
            )
        return [{"id": i, "name": n, "photos": by_person.get(i, [])} for i, n in people]

    def delete_person(self, person_id: int) -> bool:
        with self._lock:
            paths = self._db.execute(
                "SELECT path FROM face_photos WHERE person_id = ?", (person_id,)
            ).fetchall()
            self._db.execute("DELETE FROM face_photos WHERE person_id = ?", (person_id,))
            cur = self._db.execute("DELETE FROM people WHERE id = ?", (person_id,))
            self._db.commit()
        for (path,) in paths:
            (self.data_dir / path).unlink(missing_ok=True)
        return cur.rowcount > 0

    def add_face_photo(self, person_id: int, jpeg: bytes, source: str) -> str:
        photo_id = uuid.uuid4().hex
        rel = f"faces/{person_id}/{photo_id}.jpg"
        path = self.data_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(jpeg)
        with self._lock:
            self._db.execute(
                "INSERT INTO face_photos (id, person_id, path, source, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (photo_id, person_id, rel, source, time.time()),
            )
            self._db.commit()
        return photo_id

    def face_photo_path(self, photo_id: str) -> Path | None:
        with self._lock:
            row = self._db.execute(
                "SELECT path FROM face_photos WHERE id = ?", (photo_id,)
            ).fetchone()
        return self.data_dir / row[0] if row else None

    def set_face_photo_status(self, photo_id: str, status: str) -> bool:
        if status not in PHOTO_STATUSES:
            raise ValueError(f"status inválido: {status}")
        with self._lock:
            cur = self._db.execute(
                "UPDATE face_photos SET status = ? WHERE id = ?", (status, photo_id)
            )
            self._db.commit()
        return cur.rowcount > 0

    def delete_face_photo(self, photo_id: str) -> bool:
        path = self.face_photo_path(photo_id)
        with self._lock:
            cur = self._db.execute("DELETE FROM face_photos WHERE id = ?", (photo_id,))
            self._db.commit()
        if path:
            path.unlink(missing_ok=True)
        return cur.rowcount > 0

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
        subject=r[10],
        received_at=r[11] or 0.0,
    )
