"""Persistent host-owned state shared by all media source plugins.

The store deliberately contains only snapshots and playback metadata.  Source
cache databases remain private to their plugin and can be removed without
affecting history or favorites.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path


class HostStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self):
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS history(
                    source_id TEXT NOT NULL, media_id TEXT NOT NULL, entity_kind TEXT NOT NULL,
                    title TEXT NOT NULL, snapshot TEXT NOT NULL, position REAL NOT NULL DEFAULT 0,
                    duration REAL, completed INTEGER NOT NULL DEFAULT 0,
                    last_played_at REAL NOT NULL, last_checkpoint_at REAL NOT NULL,
                    PRIMARY KEY(source_id, media_id, entity_kind)
                );
                CREATE TABLE IF NOT EXISTS favorites(
                    source_id TEXT NOT NULL, media_id TEXT NOT NULL, entity_kind TEXT NOT NULL,
                    title TEXT NOT NULL, snapshot TEXT NOT NULL, favorited_at REAL NOT NULL,
                    PRIMARY KEY(source_id, media_id, entity_kind)
                );
                CREATE INDEX IF NOT EXISTS idx_history_played ON history(source_id, last_played_at DESC);
                CREATE INDEX IF NOT EXISTS idx_favorites_added ON favorites(source_id, favorited_at DESC);
            """)

    @staticmethod
    def _snapshot(data: dict | None) -> str:
        return json.dumps(data or {}, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _decode(row):
        value = dict(row)
        try:
            value["snapshot"] = json.loads(value["snapshot"])
        except (TypeError, ValueError):
            value["snapshot"] = {}
        value["completed"] = bool(value["completed"])
        return value

    def record_play(self, source_id: str, media_id: str, entity_kind: str, *, title: str,
                    snapshot: dict | None = None, position: float = 0, duration: float | None = None):
        now = time.time()
        with self._lock, self._connect() as db:
            previous = db.execute("SELECT position,duration FROM history WHERE source_id=? AND media_id=? AND entity_kind=?",
                                  (source_id, media_id, entity_kind)).fetchone()
            db.execute("""INSERT INTO history
                (source_id,media_id,entity_kind,title,snapshot,position,duration,completed,last_played_at,last_checkpoint_at)
                VALUES(?,?,?,?,?,?,?,0,?,?)
                ON CONFLICT(source_id,media_id,entity_kind) DO UPDATE SET
                title=excluded.title,snapshot=excluded.snapshot,position=excluded.position,
                duration=COALESCE(excluded.duration,history.duration),completed=0,
                last_played_at=excluded.last_played_at,last_checkpoint_at=excluded.last_checkpoint_at""",
                (source_id, media_id, entity_kind, title, self._snapshot(snapshot), float(position or 0),
                 duration if duration is not None else (previous["duration"] if previous else None), now, now))

    def checkpoint(self, source_id: str, media_id: str, entity_kind: str, *, position: float,
                   duration: float | None = None, completed: bool | None = None,
                   title: str | None = None, snapshot: dict | None = None):
        now = time.time()
        with self._lock, self._connect() as db:
            fields = ["position=?", "last_checkpoint_at=?"]
            values: list = [max(0.0, float(position or 0)), now]
            if duration is not None:
                fields.append("duration=?"); values.append(float(duration))
            if completed is not None:
                fields.append("completed=?"); values.append(int(completed))
            if title is not None:
                fields.append("title=?"); values.append(title)
            if snapshot is not None:
                fields.append("snapshot=?"); values.append(self._snapshot(snapshot))
            values.extend((source_id, media_id, entity_kind))
            db.execute(f"UPDATE history SET {','.join(fields)} WHERE source_id=? AND media_id=? AND entity_kind=?", values)

    def resume(self, source_id: str, media_id: str, entity_kind: str | None = None):
        with self._connect() as db:
            if entity_kind:
                row = db.execute("SELECT * FROM history WHERE source_id=? AND media_id=? AND entity_kind=?",
                                 (source_id, media_id, entity_kind)).fetchone()
            else:
                row = db.execute("SELECT * FROM history WHERE source_id=? AND media_id=? ORDER BY last_played_at DESC LIMIT 1",
                                 (source_id, media_id)).fetchone()
        return self._decode(row) if row else None

    def history(self, source_id: str | None = None):
        query = "SELECT * FROM history"; params = ()
        if source_id is not None:
            query += " WHERE source_id=?"; params = (source_id,)
        query += " ORDER BY last_played_at DESC"
        with self._connect() as db:
            return [self._decode(row) for row in db.execute(query, params)]

    list_history = history

    def remove_history(self, source_id: str, media_id: str, entity_kind: str | None = None):
        with self._lock, self._connect() as db:
            if entity_kind:
                db.execute("DELETE FROM history WHERE source_id=? AND media_id=? AND entity_kind=?",
                           (source_id, media_id, entity_kind))
            else:
                db.execute("DELETE FROM history WHERE source_id=? AND media_id=?", (source_id, media_id))

    def clear_history(self, source_id: str | None = None):
        with self._lock, self._connect() as db:
            if source_id is None: db.execute("DELETE FROM history")
            else: db.execute("DELETE FROM history WHERE source_id=?", (source_id,))

    def is_favorite(self, source_id: str, media_id: str, entity_kind: str):
        with self._connect() as db:
            return db.execute("SELECT 1 FROM favorites WHERE source_id=? AND media_id=? AND entity_kind=?",
                              (source_id, media_id, entity_kind)).fetchone() is not None

    def toggle_favorite(self, source_id: str, media_id: str, entity_kind: str, *, title: str,
                        snapshot: dict | None = None, favorite: bool | None = None):
        with self._lock, self._connect() as db:
            exists = db.execute("SELECT 1 FROM favorites WHERE source_id=? AND media_id=? AND entity_kind=?",
                                (source_id, media_id, entity_kind)).fetchone() is not None
            wanted = not exists if favorite is None else bool(favorite)
            if wanted:
                db.execute("""INSERT INTO favorites VALUES(?,?,?,?,?,?)
                    ON CONFLICT(source_id,media_id,entity_kind) DO UPDATE SET
                    title=excluded.title,snapshot=excluded.snapshot""",
                    (source_id, media_id, entity_kind, title, self._snapshot(snapshot), time.time()))
            else:
                db.execute("DELETE FROM favorites WHERE source_id=? AND media_id=? AND entity_kind=?",
                           (source_id, media_id, entity_kind))
            return wanted

    def favorites(self, source_id: str | None = None):
        query = "SELECT * FROM favorites"; params = ()
        if source_id is not None:
            query += " WHERE source_id=?"; params = (source_id,)
        query += " ORDER BY favorited_at DESC"
        with self._connect() as db:
            values = []
            for row in db.execute(query, params):
                value = dict(row)
                try: value["snapshot"] = json.loads(value["snapshot"])
                except (TypeError, ValueError): value["snapshot"] = {}
                values.append(value)
            return values

    list_favorites = favorites

    def set_favorite(self, source_id, media_id, entity_kind, *, title, snapshot=None, favorite=True):
        return self.toggle_favorite(source_id, media_id, entity_kind, title=title,
                                    snapshot=snapshot, favorite=favorite)

    def save_checkpoint(self, *args, **kwargs):
        return self.checkpoint(*args, **kwargs)
