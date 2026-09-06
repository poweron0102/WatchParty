from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from playback.models import (OriginPresentation, OriginRepresentation, OriginSegment,
                             OriginTrack, SegmentArtifact, SegmentDemand)


SCHEMA = 1


class CrunchyrollCache:
    """Source-owned segment index and blob store."""

    def __init__(self, root: str | Path, source_id: str):
        self.root = Path(root).resolve() / ".crunchyroll"
        self.source_id = source_id
        self.db_path = self.root / "cache.sqlite3"
        self.segments = self.root / "segments"
        self.incoming = self.root / "incoming"
        self.attachments = self.root / "attachments"
        self.export_temp = self.root / "exports-temp"
        for path in (self.root, self.segments, self.incoming, self.attachments, self.export_temp):
            path.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._leases: set[str] = set()
        self._initialize()
        self.reconcile()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self):
        with self._connect() as db:
            existing_schema = db.execute("SELECT value FROM metadata WHERE key='schema'").fetchone() if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='metadata'").fetchone() else None
            existing_source = db.execute("SELECT value FROM metadata WHERE key='source_id'").fetchone() if existing_schema is not None else None
            if existing_schema is not None and existing_schema["value"] != str(SCHEMA):
                raise RuntimeError("schema de cache incompatível")
            if existing_source is not None and existing_source["value"] != self.source_id:
                raise RuntimeError("cache_path já pertence a outra instância de Source")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS media(
                    media_id TEXT PRIMARY KEY, title TEXT NOT NULL, revision TEXT NOT NULL,
                    duration REAL NOT NULL, canonical_representation TEXT, updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tracks(
                    media_id TEXT NOT NULL, revision TEXT NOT NULL, track_id TEXT NOT NULL,
                    kind TEXT NOT NULL, language TEXT, label TEXT, is_default INTEGER NOT NULL,
                    PRIMARY KEY(media_id, revision, track_id)
                );
                CREATE TABLE IF NOT EXISTS representations(
                    media_id TEXT NOT NULL, revision TEXT NOT NULL, track_id TEXT NOT NULL, rep_id TEXT NOT NULL,
                    bandwidth INTEGER NOT NULL, codecs TEXT NOT NULL, mime_type TEXT NOT NULL,
                    width INTEGER, height INTEGER, initialization TEXT NOT NULL, segment_count INTEGER NOT NULL,
                    PRIMARY KEY(media_id, revision, track_id, rep_id)
                );
                CREATE TABLE IF NOT EXISTS segment_plan(
                    media_id TEXT NOT NULL, revision TEXT NOT NULL, track_id TEXT NOT NULL, rep_id TEXT NOT NULL,
                    identity TEXT NOT NULL, start REAL, duration REAL,
                    PRIMARY KEY(media_id, revision, track_id, rep_id, identity)
                );
                CREATE TABLE IF NOT EXISTS segments(
                    media_id TEXT NOT NULL, revision TEXT NOT NULL, track_id TEXT NOT NULL, rep_id TEXT NOT NULL,
                    identity TEXT NOT NULL, path TEXT NOT NULL, content_type TEXT NOT NULL,
                    size INTEGER NOT NULL, sha256 TEXT NOT NULL, created_at REAL NOT NULL, last_access REAL NOT NULL,
                    PRIMARY KEY(media_id, revision, track_id, rep_id, identity)
                );
                CREATE TABLE IF NOT EXISTS attachments(
                    id TEXT PRIMARY KEY, media_id TEXT NOT NULL, language TEXT NOT NULL, label TEXT NOT NULL,
                    original_path TEXT NOT NULL, vtt_path TEXT NOT NULL, original_type TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS exports(
                    id TEXT PRIMARY KEY, media_id TEXT NOT NULL, revision TEXT NOT NULL, path TEXT NOT NULL,
                    size INTEGER NOT NULL, sha256 TEXT NOT NULL, created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS catalog_edges(
                    parent_id TEXT NOT NULL, child_id TEXT NOT NULL, title TEXT NOT NULL, entry_type TEXT NOT NULL,
                    updated_at REAL NOT NULL, entity_kind TEXT, image TEXT, poster TEXT, thumbnail TEXT,
                    PRIMARY KEY(parent_id, child_id)
                );
                CREATE INDEX IF NOT EXISTS idx_segments_media ON segments(media_id, revision);
                CREATE INDEX IF NOT EXISTS idx_rep_height ON representations(height);
            """)
            db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('schema',?)", (str(SCHEMA),))
            db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('source_id',?)", (self.source_id,))
            columns = {row["name"] for row in db.execute("PRAGMA table_info(catalog_edges)")}
            for name, definition in (("entity_kind", "TEXT"), ("image", "TEXT"),
                                     ("poster", "TEXT"), ("thumbnail", "TEXT")):
                if name not in columns:
                    db.execute(f"ALTER TABLE catalog_edges ADD COLUMN {name} {definition}")

    def reconcile(self):
        for folder in (self.incoming, self.export_temp):
            for path in folder.iterdir():
                if not path.is_file(): continue
                if folder == self.incoming and path.suffix != ".tmp": continue
                try: path.unlink()
                except OSError: pass
        with self._connect() as db:
            rows = db.execute("SELECT media_id,revision,track_id,rep_id,identity,path,size FROM segments").fetchall()
            for row in rows:
                path = Path(row["path"])
                try: valid = path.is_file() and path.stat().st_size == row["size"]
                except OSError: valid = False
                if not valid:
                    db.execute("DELETE FROM segments WHERE media_id=? AND revision=? AND track_id=? AND rep_id=? AND identity=?",
                               tuple(row[key] for key in ("media_id", "revision", "track_id", "rep_id", "identity")))

    def remember(self, presentation: OriginPresentation, title: str | None = None):
        now = time.time(); revision = presentation.revision_seed
        with self._lock, self._connect() as db:
            previous = db.execute("SELECT title FROM media WHERE media_id=?", (presentation.media_id,)).fetchone()
            actual_title = title or (previous["title"] if previous else presentation.title)
            db.execute("INSERT OR REPLACE INTO media VALUES(?,?,?,?,?,?)", (
                presentation.media_id, actual_title, revision, presentation.duration,
                presentation.canonical_video_representation, now))
            db.execute("DELETE FROM tracks WHERE media_id=? AND revision=?", (presentation.media_id, revision))
            db.execute("DELETE FROM representations WHERE media_id=? AND revision=?", (presentation.media_id, revision))
            db.execute("DELETE FROM segment_plan WHERE media_id=? AND revision=?", (presentation.media_id, revision))
            for track in presentation.tracks:
                db.execute("INSERT INTO tracks VALUES(?,?,?,?,?,?,?)", (
                    presentation.media_id, revision, track.id, track.kind, track.language, track.label, int(track.default)))
                for rep in track.representations:
                    identities = ((rep.initialization, None, None), *((s.identity, s.start, s.duration) for s in rep.segments))
                    db.execute("INSERT INTO representations VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                        presentation.media_id, revision, track.id, rep.id, rep.bandwidth, rep.codecs,
                        rep.mime_type, rep.width, rep.height, rep.initialization, len(identities)))
                    db.executemany("INSERT INTO segment_plan VALUES(?,?,?,?,?,?,?)", (
                        (presentation.media_id, revision, track.id, rep.id, identity, start, duration)
                        for identity, start, duration in identities))

    def update_title(self, media_id: str, title: str):
        with self._connect() as db:
            db.execute("UPDATE media SET title=?, updated_at=? WHERE media_id=?", (title, time.time(), media_id))

    def load_presentation(self, media_id: str) -> OriginPresentation | None:
        with self._connect() as db:
            media = db.execute("SELECT * FROM media WHERE media_id=?", (media_id,)).fetchone()
            if not media:
                return None
            tracks = []
            for track in db.execute(
                    "SELECT * FROM tracks WHERE media_id=? AND revision=? ORDER BY rowid",
                    (media_id, media["revision"])):
                representations = []
                for rep in db.execute(
                        """SELECT * FROM representations
                           WHERE media_id=? AND revision=? AND track_id=? ORDER BY rowid""",
                        (media_id, media["revision"], track["track_id"])):
                    segments = tuple(OriginSegment(row["identity"], row["start"], row["duration"])
                        for row in db.execute(
                            """SELECT identity,start,duration FROM segment_plan
                               WHERE media_id=? AND revision=? AND track_id=? AND rep_id=?
                                 AND start IS NOT NULL AND duration IS NOT NULL ORDER BY rowid""",
                            (media_id, media["revision"], track["track_id"], rep["rep_id"])))
                    representations.append(OriginRepresentation(
                        rep["rep_id"], rep["bandwidth"], rep["codecs"], rep["mime_type"],
                        rep["initialization"], segments, rep["width"], rep["height"]))
                tracks.append(OriginTrack(
                    track["track_id"], track["kind"], tuple(representations),
                    track["language"], track["label"], bool(track["is_default"])))
            if not tracks:
                return None
            return OriginPresentation(
                media_id, media["title"], media["duration"], tuple(tracks), media["revision"],
                canonical_video_representation=media["canonical_representation"])

    def remember_catalog(self, parent_id: str | None, items, image_urls=None):
        parent = parent_id or "__root__"; now = time.time()
        image_urls = image_urls or {}

        def resource_data(resource):
            if resource is None:
                return None
            return {
                "id": resource.id,
                "content_type": resource.content_type,
                "size": resource.size,
                "revision": resource.revision,
                "url": image_urls.get(resource.id),
            }

        with self._connect() as db:
            db.execute("DELETE FROM catalog_edges WHERE parent_id=?", (parent,))
            db.executemany("""INSERT INTO catalog_edges
                (parent_id,child_id,title,entry_type,updated_at,entity_kind,image,poster,thumbnail)
                VALUES(?,?,?,?,?,?,?,?,?)""", (
                (parent, item.id, item.title, item.entry_type.value, now,
                 item.entity_kind or (item.id.split(":", 1)[0] if ":" in item.id else None),
                 json.dumps(resource_data(item.image), ensure_ascii=False),
                 json.dumps(resource_data(item.poster), ensure_ascii=False),
                 json.dumps(resource_data(item.thumbnail), ensure_ascii=False))
                for item in items))

    def update_catalog_images(self, child_id, image=None, poster=None, thumbnail=None, image_urls=None):
        image_urls = image_urls or {}

        def resource_data(resource):
            if resource is None:
                return None
            return json.dumps({"id": resource.id, "content_type": resource.content_type,
                               "size": resource.size, "revision": resource.revision,
                               "url": image_urls.get(resource.id)}, ensure_ascii=False)

        with self._connect() as db:
            db.execute("""UPDATE catalog_edges SET image=?,poster=?,thumbnail=?
                          WHERE child_id=?""",
                       (resource_data(image), resource_data(poster), resource_data(thumbnail), child_id))

    def descendants(self, parent_id: str) -> list[str]:
        with self._connect() as db:
            rows = db.execute("""WITH RECURSIVE tree(id,entry_type) AS (
                SELECT child_id,entry_type FROM catalog_edges WHERE parent_id=?
                UNION ALL
                SELECT e.child_id,e.entry_type FROM catalog_edges e JOIN tree t ON e.parent_id=t.id
            ) SELECT DISTINCT id FROM tree WHERE entry_type='playable'""", (parent_id,)).fetchall()
            return [row["id"] for row in rows]

    def export_hierarchy(self, media_id: str) -> list[str]:
        hierarchy: list[str] = []; child = media_id; seen = set()
        with self._connect() as db:
            while child not in seen:
                seen.add(child)
                rows = db.execute("SELECT parent_id,title FROM catalog_edges WHERE child_id=? ORDER BY CASE WHEN parent_id LIKE 'root:%' THEN 1 ELSE 0 END", (child,)).fetchall()
                if not rows: break
                parent = rows[0]["parent_id"]
                if child != media_id: hierarchy.insert(0, rows[0]["title"])
                if parent == "__root__" or parent.startswith("root:"): break
                child = parent
        return hierarchy[-2:]

    def revision_for(self, media_id: str) -> str | None:
        with self._connect() as db:
            row = db.execute("SELECT revision FROM media WHERE media_id=?", (media_id,)).fetchone()
            return row["revision"] if row else None

    @staticmethod
    def _key(media_id: str, revision: str, demand: SegmentDemand) -> str:
        raw = "\0".join((media_id, revision, demand.track_id, demand.representation_id, demand.segment_identity))
        return hashlib.sha256(raw.encode()).hexdigest()

    def _managed_segment(self, value: str | Path) -> Path | None:
        try:
            path = Path(value).resolve(); path.relative_to(self.segments.resolve()); return path
        except (OSError, RuntimeError, ValueError):
            return None

    def locate(self, media_id: str, demand: SegmentDemand) -> SegmentArtifact | None:
        revision = self.revision_for(media_id)
        if not revision: return None
        with self._connect() as db:
            row = db.execute("""SELECT path,content_type,size,sha256 FROM segments
                WHERE media_id=? AND revision=? AND track_id=? AND rep_id=? AND identity=?""",
                (media_id, revision, demand.track_id, demand.representation_id, demand.segment_identity)).fetchone()
            if not row: return None
            path = self._managed_segment(row["path"])
            if path is None: return None
            try:
                if not path.is_file() or path.stat().st_size != row["size"]: return None
            except OSError: return None
            db.execute("""UPDATE segments SET last_access=? WHERE media_id=? AND revision=? AND track_id=? AND rep_id=? AND identity=?""",
                       (time.time(), media_id, revision, demand.track_id, demand.representation_id, demand.segment_identity))
            return SegmentArtifact(path, row["content_type"], row["size"], row["sha256"])

    def publish(self, media_id: str, demand: SegmentDemand, artifact: SegmentArtifact) -> SegmentArtifact:
        revision = self.revision_for(media_id)
        if not revision: raise RuntimeError("apresentação não foi registrada")
        existing = self.locate(media_id, demand)
        if existing: return existing
        raw = artifact.path.read_bytes(); digest = hashlib.sha256(raw).hexdigest()
        if digest != artifact.sha256 or len(raw) != artifact.size: raise ValueError("artefato inválido")
        key = self._key(media_id, revision, demand); destination = self.segments / key[:2] / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.incoming / f"{secrets.token_hex(16)}.tmp"
        with self._lock:
            existing = self.locate(media_id, demand)
            if existing: return existing
            temporary.write_bytes(raw); os.replace(temporary, destination)
            now = time.time()
            with self._connect() as db:
                db.execute("INSERT OR REPLACE INTO segments VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                    media_id, revision, demand.track_id, demand.representation_id, demand.segment_identity,
                    str(destination), artifact.content_type, len(raw), digest, now, now))
        try:
            if artifact.path.resolve().is_relative_to(self.incoming): artifact.path.unlink(missing_ok=True)
        except (OSError, ValueError): pass
        return SegmentArtifact(destination, artifact.content_type, len(raw), digest)

    @contextmanager
    def lease(self, artifacts: list[SegmentArtifact]):
        paths = {str(item.path.resolve()) for item in artifacts}
        with self._lock: self._leases.update(paths)
        try: yield
        finally:
            with self._lock: self._leases.difference_update(paths)

    def attachments_for(self, media_id: str):
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM attachments WHERE media_id=? ORDER BY created_at", (media_id,))]

    def add_attachment(self, media_id: str, language: str, label: str, original: Path, vtt: Path, original_type: str):
        attachment_id = hashlib.sha256(f"{media_id}\0{language}\0{time.time_ns()}".encode()).hexdigest()[:24]
        with self._connect() as db:
            db.execute("INSERT INTO attachments VALUES(?,?,?,?,?,?,?,?)", (
                attachment_id, media_id, language, label, str(original), str(vtt), original_type, time.time()))
        return attachment_id

    def register_export(self, media_id: str, revision: str, path: Path, digest: str):
        with self._connect() as db:
            db.execute("INSERT INTO exports VALUES(?,?,?,?,?,?,?)", (
                secrets.token_hex(12), media_id, revision, str(path), path.stat().st_size, digest, time.time()))

    def inventory(self):
        with self._connect() as db:
            media_rows = db.execute("SELECT * FROM media ORDER BY title COLLATE NOCASE").fetchall()
            result = []
            for media in media_rows:
                plan = db.execute("SELECT COUNT(*) count FROM segment_plan WHERE media_id=? AND revision=?",
                                  (media["media_id"], media["revision"])).fetchone()["count"]
                cached = db.execute("SELECT COUNT(*) count,COALESCE(SUM(size),0) bytes FROM segments WHERE media_id=? AND revision=?",
                                    (media["media_id"], media["revision"])).fetchone()
                tracks = []
                for track in db.execute("SELECT * FROM tracks WHERE media_id=? AND revision=? ORDER BY kind,language",
                                        (media["media_id"], media["revision"])):
                    reps = []
                    for rep in db.execute("SELECT * FROM representations WHERE media_id=? AND revision=? AND track_id=?",
                                          (media["media_id"], media["revision"], track["track_id"])):
                        ready = db.execute("SELECT COUNT(*) count,COALESCE(SUM(size),0) bytes FROM segments WHERE media_id=? AND revision=? AND track_id=? AND rep_id=?",
                                           (media["media_id"], media["revision"], track["track_id"], rep["rep_id"])).fetchone()
                        reps.append({**dict(rep), "cached_count": ready["count"], "cached_bytes": ready["bytes"],
                                     "coverage": ready["count"] / rep["segment_count"] if rep["segment_count"] else 0})
                    tracks.append({**dict(track), "representations": reps})
                exports = [dict(row) for row in db.execute("SELECT * FROM exports WHERE media_id=? ORDER BY created_at DESC", (media["media_id"],))]
                state = self._media_state(db, media)
                result.append({**dict(media), "cached_count": cached["count"], "cached_bytes": cached["bytes"],
                               "coverage": cached["count"] / plan if plan else 0, "state": state,
                               "tracks": tracks, "exports": exports})
            return result

    @staticmethod
    def _valid_export(row) -> bool:
        path = Path(row["path"])
        try:
            if not path.is_file() or path.stat().st_size != row["size"]: return False
            value = hashlib.sha256()
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024): value.update(chunk)
            digest = value.hexdigest()
            return digest == row["sha256"]
        except OSError: return False

    @staticmethod
    def _has_complete_representation(db, media_id: str, revision: str, kind: str,
                                     representation_id: str | None = None) -> bool:
        query = """SELECT r.segment_count,COUNT(s.identity) cached FROM representations r
            LEFT JOIN segments s ON s.media_id=r.media_id AND s.revision=r.revision
                AND s.track_id=r.track_id AND s.rep_id=r.rep_id
            JOIN tracks t ON t.media_id=r.media_id AND t.revision=r.revision AND t.track_id=r.track_id
            WHERE r.media_id=? AND r.revision=? AND t.kind=?"""
        params: list[object] = [media_id, revision, kind]
        if representation_id is not None:
            query += " AND r.rep_id=?"
            params.append(representation_id)
        # segment_count 0 significa plano desconhecido, nao "nada a baixar":
        # sem esta guarda, `cached >= segment_count` daria 0 >= 0 e uma midia
        # sem plano seria declarada completa.
        query += " AND r.segment_count > 0 GROUP BY r.track_id,r.rep_id,r.segment_count"
        return any(row["cached"] >= row["segment_count"] for row in db.execute(query, params))

    def _media_state(self, db, media_row) -> str:
        """`empty` | `partial` | `offline` | `exported` para uma midia.

        Definicao unica: o inventario completo e o resumo por colecao chegavam
        ao mesmo rotulo por caminhos diferentes, que e como duas telas passam
        a discordar sobre a mesma midia.
        """
        media_id, revision = media_row["media_id"], media_row["revision"]
        exports = db.execute("SELECT * FROM exports WHERE media_id=?", (media_id,)).fetchall()
        if any(self._valid_export(row) for row in exports):
            return "exported"
        video_complete = self._has_complete_representation(
            db, media_id, revision, "video", media_row["canonical_representation"])
        audio_complete = self._has_complete_representation(db, media_id, revision, "audio")
        if video_complete and audio_complete:
            return "offline"
        cached = db.execute("SELECT COUNT(*) count FROM segments WHERE media_id=? AND revision=?",
                            (media_id, revision)).fetchone()["count"]
        return "partial" if cached else "empty"

    def collection_summary(self, parent_id: str):
        """Estado de cache agregado dos episodios sob `parent_id`.

        Existe porque o Inspetor de uma serie precisa falar da serie aberta.
        Antes, o plugin pedia o inventario inteiro e filtrava por
        `media_id.startsWith('episode:')` -- ou seja, contava TODOS os
        episodios em cache de TODAS as series, e mostrava esse numero como se
        fosse da entidade aberta.  A hierarquia mora no banco; o prefixo do id
        nunca soube quem e filho de quem.
        """
        media_ids = self.descendants(str(parent_id or ""))
        counts = {"empty": 0, "partial": 0, "offline": 0, "exported": 0}
        cached_bytes = 0
        if not media_ids:
            return {"total": 0, "known": 0, "cached_bytes": 0, **counts}
        with self._connect() as db:
            placeholders = ",".join("?" for _ in media_ids)
            rows = db.execute(f"SELECT * FROM media WHERE media_id IN ({placeholders})", media_ids).fetchall()
            for row in rows:
                counts[self._media_state(db, row)] += 1
                cached_bytes += db.execute(
                    "SELECT COALESCE(SUM(size),0) bytes FROM segments WHERE media_id=? AND revision=?",
                    (row["media_id"], row["revision"])).fetchone()["bytes"]
        # `total` conta os episodios da colecao; `known` so os que o cache ja
        # viu.  A diferenca sao os que nunca foram tocados -- que continuam
        # sendo "sem cache", e por isso entram em `empty`.
        counts["empty"] += len(media_ids) - len(rows)
        return {"total": len(media_ids), "known": len(rows), "cached_bytes": cached_bytes, **counts}

    def cleanup_preview(self, filters: dict):
        mode = filters.get("mode", "all"); params: list[object] = []
        query = """SELECT s.*,r.height FROM segments s LEFT JOIN representations r
            ON r.media_id=s.media_id AND r.revision=s.revision AND r.track_id=s.track_id AND r.rep_id=s.rep_id WHERE 1=1"""
        with self._connect() as db:
            if mode == "quality":
                query += " AND r.height=?"; params.append(int(filters.get("height", 0)))
            elif mode == "media":
                values = [str(value) for value in filters.get("media_ids", [])]
                if not values: return {"count": 0, "bytes": 0, "media": [], "paths": []}
                query += f" AND s.media_id IN ({','.join('?' for _ in values)})"; params.extend(values)
            elif mode == "collection":
                values = self.descendants(str(filters.get("parent_id", "")))
                if not values: return {"count": 0, "bytes": 0, "media": [], "paths": []}
                query += f" AND s.media_id IN ({','.join('?' for _ in values)})"; params.extend(values)
            elif mode == "partial":
                cutoff = time.time() - max(0, float(filters.get("older_than_days", 30))) * 86400
                partial = []
                for row in db.execute("SELECT media_id,revision,canonical_representation FROM media"):
                    cached = db.execute("SELECT COUNT(*) count FROM segments WHERE media_id=? AND revision=?",
                                        (row["media_id"], row["revision"])).fetchone()["count"]
                    if not cached:
                        continue
                    video_complete = self._has_complete_representation(
                        db, row["media_id"], row["revision"], "video", row["canonical_representation"])
                    audio_complete = self._has_complete_representation(
                        db, row["media_id"], row["revision"], "audio")
                    if not (video_complete and audio_complete):
                        partial.append(row["media_id"])
                if not partial: return {"count": 0, "bytes": 0, "media": [], "paths": []}
                query += f" AND s.last_access<? AND s.media_id IN ({','.join('?' for _ in partial)})"; params.extend([cutoff, *partial])
            elif mode == "exported":
                exported = {row["media_id"] for row in db.execute("SELECT * FROM exports") if self._valid_export(row)}
                if not exported: return {"count": 0, "bytes": 0, "media": [], "paths": []}
                query += f" AND s.media_id IN ({','.join('?' for _ in exported)})"; params.extend(sorted(exported))
            elif mode != "all":
                raise ValueError("filtro de limpeza desconhecido")
            rows = db.execute(query, params).fetchall()
        with self._lock:
            leased = set(self._leases)
        chosen = [(row, str(path)) for row in rows if (path := self._managed_segment(row["path"])) is not None and str(path) not in leased]
        return {"count": len(chosen), "bytes": sum(row["size"] for row, _ in chosen),
                "media": sorted({row["media_id"] for row, _ in chosen}), "paths": [path for _, path in chosen]}

    def cleanup(self, filters: dict):
        removed = skipped = bytes_removed = 0
        with self._lock:
            preview = self.cleanup_preview(filters)
            targets = set(preview["paths"])
            with self._connect() as db:
                rows = db.execute("SELECT * FROM segments").fetchall()
                for row in rows:
                    managed = self._managed_segment(row["path"])
                    if managed is None or str(managed) not in targets: continue
                    try:
                        managed.unlink(missing_ok=True)
                        db.execute("DELETE FROM segments WHERE media_id=? AND revision=? AND track_id=? AND rep_id=? AND identity=?",
                                   tuple(row[key] for key in ("media_id", "revision", "track_id", "rep_id", "identity")))
                        removed += 1; bytes_removed += row["size"]
                    except OSError: skipped += 1
        return {"removed": removed, "skipped": skipped, "bytes": bytes_removed}

    def orphan_preview(self):
        with self._connect() as db:
            known = {str(Path(row["path"]).resolve()) for row in db.execute("SELECT path FROM segments")}
        with self._lock:
            leased = set(self._leases)
        paths = []
        for path in self.segments.rglob("*"):
            if path.is_file() and str(path.resolve()) not in known and str(path.resolve()) not in leased:
                paths.append(path)
        # Mesma forma de cleanup_preview: a UI le os dois pelo mesmo caminho, e
        # `media` vazio e a resposta honesta -- orfao e justamente o arquivo
        # que nenhuma midia reivindica.
        return {"count": len(paths), "bytes": sum(path.stat().st_size for path in paths),
                "media": [], "paths": [str(path) for path in paths]}

    def remove_orphans(self):
        removed = skipped = bytes_removed = 0
        with self._lock:
            preview = self.orphan_preview()
            for value in preview["paths"]:
                path = Path(value)
                try:
                    size = path.stat().st_size
                    path.unlink()
                    removed += 1; bytes_removed += size
                except OSError:
                    skipped += 1
        # `bytes` era o total previsto, nao o recuperado: um arquivo travado
        # entrava na conta como se tivesse sido apagado.
        return {"removed": removed, "skipped": skipped, "bytes": bytes_removed}
