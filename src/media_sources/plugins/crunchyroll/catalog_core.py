from __future__ import annotations

import json
import hashlib
import asyncio
import httpx
import secrets
import time
from pathlib import Path
from urllib.parse import quote

from .api import CrunchyrollApi
from media_sources.errors import CollectionNotFound, MediaItemNotFound, ResourceNotFound, SourceUnavailable
from media_sources.models import CatalogEntry, CatalogPage, EntryType, MediaItem, MediaResource
from media_sources.models import OpenedResource
from .worker_client import CrunchyrollWorkerClient


class CrunchyrollSource:
    ROOTS = (("popular", "Popular"), ("new", "Novidades"), ("seasonal", "Temporada"),
             ("az", "A-Z"), ("genres", "Gêneros"))

    def __init__(self, cache_path: Path, etp_rt: str, locale: str, metadata_ttl_hours: int,
                 api: CrunchyrollApi | None = None, worker_path=None, worker_options=None):
        self.cache_path = cache_path.resolve(); self.cache_path.mkdir(parents=True, exist_ok=True)
        self._metadata = self.cache_path / ".crunchyroll" / "manifests" / "catalog"
        self._metadata.mkdir(parents=True, exist_ok=True)
        self._images = self.cache_path / ".crunchyroll" / "images"
        self._images.mkdir(parents=True, exist_ok=True)
        self._api = api or CrunchyrollApi(etp_rt, locale)
        self._ttl = metadata_ttl_hours * 3600
        self._image_urls = {}
        self._image_locks = {}
        self._worker = CrunchyrollWorkerClient(worker_path, etp_rt, worker_options or {}) if worker_path else None

    @property
    def playback_available(self): return self._worker is not None and Path(self._worker.path).is_file()

    async def inspect(self, media_id):
        if not self._worker: raise SourceUnavailable("worker de playback indisponível")
        return await self._worker.inspect(self._remote_id(media_id))

    async def materialize(self, media_id, demand):
        if not self._worker: raise SourceUnavailable("worker de playback indisponível")
        return await self._worker.materialize(self._remote_id(media_id), demand)

    @staticmethod
    def _remote_id(local_id: str) -> str:
        prefix, separator, remote_id = local_id.partition(":")
        if separator and prefix in {"series", "season", "episode", "movie"}: return remote_id
        return local_id

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

    @staticmethod
    def _image_url(images, preferred=("poster_tall", "thumbnail", "poster_wide", "promo_image")) -> str | None:
        if isinstance(images, dict):
            if isinstance(images.get("source"), str): return images["source"]
            for key in preferred:
                found = CrunchyrollSource._image_url(images.get(key), preferred)
                if found: return found
            for value in images.values():
                found = CrunchyrollSource._image_url(value, preferred)
                if found: return found
        elif isinstance(images, list):
            for value in reversed(images):
                found = CrunchyrollSource._image_url(value, preferred)
                if found: return found
        return None

    def _image_resource(self, image_url: str | None):
        if not image_url: return None
        opaque = hashlib.sha256(image_url.encode()).hexdigest()
        self._image_urls[opaque] = image_url
        return MediaResource(f"image:{opaque}", "image/jpeg", revision=opaque)

    @staticmethod
    def _payload_items(payload):
        results = payload.get("data") or payload.get("items") or []
        flattened = []
        for raw in results:
            if isinstance(raw, dict) and not (raw.get("id") or raw.get("series_id")) and isinstance(raw.get("items"), list):
                flattened.extend(item for item in raw["items"] if isinstance(item, dict))
            elif isinstance(raw, dict): flattened.append(raw)
        return flattened

    def _entries(self, payload, expected_type=None) -> tuple[CatalogEntry, ...]:
        entries = []
        for raw in self._payload_items(payload):
            identifier = raw.get("id") or raw.get("series_id")
            title = raw.get("title") or raw.get("name")
            if not identifier or not title: continue
            kind = expected_type or raw.get("type") or ("episode" if raw.get("episode_number") is not None else "series")
            is_playable = kind in ("movie", "episode") or raw.get("episode_number") is not None
            local_kind = "episode" if is_playable and kind != "movie" else kind
            if local_kind not in {"series", "season", "episode", "movie"}: local_kind = "series"
            images = raw.get("images") or raw.get("localized_images") or {}
            poster = self._image_resource(self._image_url(images, ("poster_tall", "poster_wide", "promo_image", "thumbnail")))
            thumbnail = self._image_resource(self._image_url(images, ("thumbnail", "promo_image", "poster_wide", "poster_tall")))
            image = thumbnail if is_playable else poster
            entries.append(CatalogEntry(f"{local_kind}:{identifier}", str(title), EntryType.PLAYABLE if is_playable else EntryType.COLLECTION,
                                        "video" if is_playable else None, image,
                                        poster=poster, thumbnail=thumbnail, entity_kind=local_kind))
        return tuple(entries)

    async def browse(self, parent_id=None, cursor=None):
        if parent_id is None:
            return CatalogPage(tuple(CatalogEntry(f"root:{key}", label, EntryType.COLLECTION,
                                                  entity_kind="view") for key, label in self.ROOTS))
        offset = int(cursor or 0)
        if parent_id.startswith("root:"):
            kind = parent_id[5:]
            params = {"n": 50, "start": offset}
            if kind == "new": params["sort_by"] = "newly_added"
            elif kind == "az": params["sort_by"] = "alphabetical"
            elif kind == "popular": params["sort_by"] = "popularity"
            payload = await self._cached(f"browse:{kind}:{offset}", lambda: self._api.get("/content/v2/discover/browse", params))
            items = self._entries(payload)
        elif parent_id.startswith("series:"):
            remote_id = self._remote_id(parent_id)
            params = {"force_locale": "", "preferred_audio_language": "ja-JP"}
            payload = await self._cached(f"seasons:{remote_id}", lambda: self._api.get(
                f"/content/v2/cms/series/{quote(remote_id)}/seasons", params))
            items = self._entries(payload, "season")
        elif parent_id.startswith("season:"):
            remote_id = self._remote_id(parent_id)
            params = {"preferred_audio_language": "ja-JP"}
            payload = await self._cached(f"episodes:{remote_id}", lambda: self._api.get(
                f"/content/v2/cms/seasons/{quote(remote_id)}/episodes", params))
            items = self._entries(payload, "episode")
        else: raise CollectionNotFound("coleção não encontrada")
        return CatalogPage(items, str(offset + len(items)) if len(items) == 50 else None)

    async def search(self, query, cursor=None):
        offset = int(cursor or 0); q = query.strip()
        if not q: return CatalogPage(())
        payload = await self._cached(f"search:{q.casefold()}:{offset}", lambda: self._api.get("/content/v2/discover/search", {"q": q, "n": 50, "start": offset}))
        items = self._entries(payload); return CatalogPage(items, str(offset + len(items)) if len(items) == 50 else None)

    async def get_item(self, media_id):
        remote_id = self._remote_id(media_id)
        payload = await self._cached(f"item:{remote_id}", lambda: self._api.get(f"/content/v2/cms/objects/{quote(remote_id)}"))
        entries = self._entries(payload)
        if not entries or entries[0].entry_type != EntryType.PLAYABLE: raise MediaItemNotFound("item não encontrado")
        entry = entries[0]
        # Playback inspection is delegated to the private worker adapter; never expose upstream URLs here.
        return MediaItem(entry.id, entry.title, MediaResource("playback", "application/dash+xml"),
                         image=entry.image, poster=entry.poster, thumbnail=entry.thumbnail)

    async def get_entity(self, entity_id):
        """Return a typed catalog entity for inspector/favorite snapshots."""
        remote_id = self._remote_id(entity_id)
        payload = await self._cached(f"entity:{remote_id}", lambda: self._api.get(
            f"/content/v2/cms/objects/{quote(remote_id)}"))
        entries = self._entries(payload)
        if not entries:
            raise MediaItemNotFound("item nÃ£o encontrado")
        return entries[0]

    async def open_resource(self, resource_id, byte_range=None):
        if not resource_id.startswith("image:"): raise ResourceNotFound("recurso não encontrado")
        opaque = resource_id[6:]
        if len(opaque) != 64 or any(value not in "0123456789abcdef" for value in opaque):
            raise ResourceNotFound("recurso não encontrado")
        path, metadata = self._images / opaque, self._images / f"{opaque}.json"
        data, content_type = self._read_cached_image(path, metadata)
        if data is None:
            url = self._image_urls.get(opaque)
            if not url: raise ResourceNotFound("recurso não encontrado")
            lock = self._image_locks.setdefault(opaque, asyncio.Lock())
            async with lock:
                data, content_type = self._read_cached_image(path, metadata)
                if data is None:
                    try:
                        async with httpx.AsyncClient(timeout=20) as client:
                            response = await client.get(url); response.raise_for_status(); data = response.content
                    except httpx.HTTPError as exc: raise SourceUnavailable("imagem temporariamente indisponível") from exc
                    content_type = response.headers.get("content-type", "image/jpeg").split(";", 1)[0].strip()
                    if not content_type.startswith("image/"): content_type = "application/octet-stream"
                    self._publish_image(path, metadata, data, content_type)
        start, end = 0, len(data) - 1
        if byte_range:
            if byte_range.suffix_length is not None: start = max(0, len(data) - byte_range.suffix_length)
            else: start, end = byte_range.start or 0, min(byte_range.end if byte_range.end is not None else end, end)
        async def chunks():
            if data: yield data[start:end + 1]
        return OpenedResource(chunks(), len(data), content_type, start, end)

    @staticmethod
    def _read_cached_image(path: Path, metadata: Path):
        try:
            data = path.read_bytes()
            details = json.loads(metadata.read_text(encoding="utf-8"))
            content_type = details.get("content_type", "image/jpeg")
            if not isinstance(content_type, str): content_type = "image/jpeg"
            return data, content_type
        except (OSError, ValueError):
            return None, None

    @staticmethod
    def _publish_image(path: Path, metadata: Path, data: bytes, content_type: str):
        token = secrets.token_hex(8)
        image_temp = path.with_name(f"{path.name}.{token}.tmp")
        metadata_temp = metadata.with_name(f"{metadata.name}.{token}.tmp")
        try:
            image_temp.write_bytes(data)
            metadata_temp.write_text(json.dumps({"content_type": content_type}), encoding="utf-8")
            image_temp.replace(path)
            metadata_temp.replace(metadata)
        finally:
            image_temp.unlink(missing_ok=True)
            metadata_temp.unlink(missing_ok=True)
