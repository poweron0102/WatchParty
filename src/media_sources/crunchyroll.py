from __future__ import annotations

import json
import hashlib
import httpx
import time
from pathlib import Path
from urllib.parse import quote

from .crunchyroll_api import CrunchyrollApi
from .errors import CollectionNotFound, MediaItemNotFound, ResourceNotFound, SourceUnavailable
from .models import CatalogEntry, CatalogPage, EntryType, MediaItem, MediaResource
from .models import OpenedResource
from .crunchyroll_worker import CrunchyrollWorkerClient


class CrunchyrollSource:
    ROOTS = (("popular", "Popular"), ("new", "Novidades"), ("seasonal", "Temporada"),
             ("az", "A-Z"), ("genres", "Gêneros"))

    def __init__(self, cache_path: Path, etp_rt: str, locale: str, metadata_ttl_hours: int,
                 api: CrunchyrollApi | None = None, worker_path=None, worker_options=None):
        self.cache_path = cache_path.resolve(); self.cache_path.mkdir(parents=True, exist_ok=True)
        self._metadata = self.cache_path / ".crunchyroll" / "manifests" / "catalog"
        self._metadata.mkdir(parents=True, exist_ok=True)
        self._api = api or CrunchyrollApi(etp_rt, locale)
        self._ttl = metadata_ttl_hours * 3600
        self._image_urls = {}
        self._worker = CrunchyrollWorkerClient(worker_path, etp_rt, worker_options or {}) if worker_path else None

    @property
    def playback_available(self): return self._worker is not None and Path(self._worker.path).is_file()

    async def inspect(self, media_id):
        if not self._worker: raise SourceUnavailable("worker de playback indisponível")
        return await self._worker.inspect(media_id)

    async def materialize(self, media_id, demand):
        if not self._worker: raise SourceUnavailable("worker de playback indisponível")
        return await self._worker.materialize(media_id, demand)

    def _cache_file(self, key: str) -> Path:
        import hashlib
        return self._metadata / f"{hashlib.sha256(key.encode()).hexdigest()}.json"

    async def _cached(self, key, loader):
        path = self._cache_file(key); stale = None
        try: stale = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError): pass
        if stale and time.time() - stale.get("stored_at", 0) <= self._ttl: return stale["payload"]
        try:
            payload = await loader()
            # Only catalog JSON is persisted; authentication and playback data never pass here.
            clean = {"stored_at": time.time(), "payload": payload}
            temp = path.with_suffix(".tmp"); temp.write_text(json.dumps(clean, ensure_ascii=False), encoding="utf-8"); temp.replace(path)
            return payload
        except SourceUnavailable:
            if stale: return stale["payload"]
            raise

    def _entries(self, payload) -> tuple[CatalogEntry, ...]:
        results = payload.get("data") or payload.get("items") or []
        entries = []
        for raw in results:
            identifier = raw.get("id") or raw.get("series_id")
            title = raw.get("title") or raw.get("name")
            if not identifier or not title: continue
            is_playable = raw.get("type") in ("movie", "episode") or raw.get("episode_number") is not None
            images = raw.get("images") or {}; image_url = None
            for group in images.values() if isinstance(images, dict) else ():
                if isinstance(group, list) and group:
                    candidate = group[-1]
                    if isinstance(candidate, dict): image_url = candidate.get("source"); break
            image = None
            if image_url:
                opaque = hashlib.sha256(image_url.encode()).hexdigest()
                self._image_urls[opaque] = image_url
                image = MediaResource(f"image:{opaque}", "image/jpeg")
            entries.append(CatalogEntry(str(identifier), str(title), EntryType.PLAYABLE if is_playable else EntryType.COLLECTION,
                                        "video" if is_playable else None, image))
        return tuple(entries)

    async def browse(self, parent_id=None, cursor=None):
        if parent_id is None:
            return CatalogPage(tuple(CatalogEntry(f"root:{key}", label, EntryType.COLLECTION) for key, label in self.ROOTS))
        offset = int(cursor or 0)
        if parent_id.startswith("root:"):
            kind = parent_id[5:]
            params = {"n": 50, "start": offset}
            if kind == "new": params["sort_by"] = "newly_added"
            elif kind == "az": params["sort_by"] = "alphabetical"
            elif kind == "popular": params["sort_by"] = "popularity"
            payload = await self._cached(f"browse:{kind}:{offset}", lambda: self._api.get("/content/v2/discover/browse", params))
        else:
            payload = await self._cached(f"object:{parent_id}", lambda: self._api.get(f"/content/v2/cms/objects/{quote(parent_id)}"))
        items = self._entries(payload); return CatalogPage(items, str(offset + len(items)) if len(items) == 50 else None)

    async def search(self, query, cursor=None):
        offset = int(cursor or 0); q = query.strip()
        if not q: return CatalogPage(())
        payload = await self._cached(f"search:{q.casefold()}:{offset}", lambda: self._api.get("/content/v2/discover/search", {"q": q, "n": 50, "start": offset}))
        items = self._entries(payload); return CatalogPage(items, str(offset + len(items)) if len(items) == 50 else None)

    async def get_item(self, media_id):
        payload = await self._cached(f"item:{media_id}", lambda: self._api.get(f"/content/v2/cms/objects/{quote(media_id)}"))
        entries = self._entries(payload)
        if not entries or entries[0].entry_type != EntryType.PLAYABLE: raise MediaItemNotFound("item não encontrado")
        entry = entries[0]
        # Playback inspection is delegated to the private worker adapter; never expose upstream URLs here.
        return MediaItem(entry.id, entry.title, MediaResource("playback", "application/dash+xml"), image=entry.image)

    async def open_resource(self, resource_id, byte_range=None):
        if not resource_id.startswith("image:"): raise ResourceNotFound("recurso não encontrado")
        url = self._image_urls.get(resource_id[6:])
        if not url: raise ResourceNotFound("recurso não encontrado")
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(url); response.raise_for_status(); data = response.content
        except httpx.HTTPError as exc: raise SourceUnavailable("imagem temporariamente indisponível") from exc
        start, end = 0, len(data) - 1
        if byte_range:
            if byte_range.suffix_length is not None: start = max(0, len(data) - byte_range.suffix_length)
            else: start, end = byte_range.start or 0, min(byte_range.end if byte_range.end is not None else end, end)
        async def chunks():
            if data: yield data[start:end + 1]
        return OpenedResource(chunks(), len(data), response.headers.get("content-type", "image/jpeg"), start, end)
