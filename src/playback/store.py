from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
from pathlib import Path

from .models import SegmentArtifact, SegmentDemand


class SegmentStore:
    """Immutable, atomic derived-asset store. Upstream details never enter metadata."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.incoming = self.root / "incoming"
        self.assets = self.root / "segments"
        self.incoming.mkdir(parents=True, exist_ok=True)
        self.assets.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    @staticmethod
    def _key(media_id: str, demand: SegmentDemand) -> str:
        value = "\0".join((media_id, demand.track_id, demand.representation_id, demand.segment_identity))
        return hashlib.sha256(value.encode()).hexdigest()

    def locate(self, media_id: str, demand: SegmentDemand) -> SegmentArtifact | None:
        key = self._key(media_id, demand)
        path, metadata = self.assets / key[:2] / key, self.assets / key[:2] / f"{key}.json"
        try:
            raw = path.read_bytes()
            data = json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        digest = hashlib.sha256(raw).hexdigest()
        if digest != data.get("sha256") or len(raw) != data.get("size"):
            return None
        return SegmentArtifact(path, data["content_type"], len(raw), digest)

    async def publish(self, media_id: str, demand: SegmentDemand, source: SegmentArtifact) -> SegmentArtifact:
        existing = self.locate(media_id, demand)
        if existing:
            return existing
        raw = await asyncio.to_thread(source.path.read_bytes)
        digest = hashlib.sha256(raw).hexdigest()
        if source.size != len(raw) or source.sha256 != digest:
            raise ValueError("artefato de segmento inválido")
        key = self._key(media_id, demand)
        destination = self.assets / key[:2] / key
        metadata = destination.with_suffix(".json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        async with self._lock:
            existing = self.locate(media_id, demand)
            if existing:
                return existing
            temp = self.incoming / f"{secrets.token_hex(16)}.part"
            temp_meta = self.incoming / f"{secrets.token_hex(16)}.json"
            await asyncio.to_thread(temp.write_bytes, raw)
            await asyncio.to_thread(temp_meta.write_text, json.dumps({
                "schema": 1, "content_type": source.content_type, "size": len(raw), "sha256": digest,
            }, separators=(",", ":")), "utf-8")
            os.replace(temp, destination)
            os.replace(temp_meta, metadata)
        return SegmentArtifact(destination, source.content_type, len(raw), digest)

    def reconcile(self) -> None:
        for path in self.incoming.glob("*.part"):
            try: path.unlink()
            except OSError: pass
