from __future__ import annotations

import mimetypes
import asyncio
from pathlib import Path, PurePosixPath

from media_sources.errors import (CollectionNotFound, InvalidByteRange, InvalidSourceConfiguration,
                                  MediaItemNotFound, ResourceNotFound, SourceReadError, SourceUnavailable)
from media_sources.models import (ByteRangeRequest, CatalogEntry, CatalogPage, EntryType, MediaItem,
                                  MediaResource, MediaTrack, OpenedResource)

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".avi"}
AUDIO_EXTENSIONS = {".mp3", ".aac", ".ogg"}
CONTENT_TYPES = {
    ".mp4": "video/mp4", ".mkv": "video/x-matroska", ".webm": "video/webm",
    ".avi": "video/x-msvideo", ".mp3": "audio/mpeg", ".aac": "audio/aac",
    ".ogg": "audio/ogg", ".vtt": "text/vtt", ".png": "image/png",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
}


class DirectorySource:
    def __init__(self, root: str | Path, ffmpeg_path="ffmpeg.exe", transcode_profile="chrome-h264-aac", hardware_acceleration="auto"):
        try:
            self._root = Path(root).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise InvalidSourceConfiguration("diretório inexistente ou inacessível") from exc
        if not self._root.is_dir():
            raise InvalidSourceConfiguration("o caminho configurado não é um diretório")

        from .playback import DirectoryPlaybackAdapter
        self._playback = DirectoryPlaybackAdapter(self._root, ffmpeg_path, transcode_profile, hardware_acceleration)

    @property
    def playback_available(self): return self._playback.available

    async def inspect(self, media_id): return await self._playback.inspect(media_id)
    async def materialize(self, media_id, demand): return await self._playback.materialize(media_id, demand)

    def _resolve(self, opaque_id: str | None, *, must_exist: bool = True) -> Path:
        if not opaque_id:
            return self._root
        candidate_id = opaque_id.replace("\\", "/")
        pure = PurePosixPath(candidate_id)
        if pure.is_absolute() or ".." in pure.parts or not pure.parts:
            raise ResourceNotFound("recurso não encontrado")
        try:
            candidate = self._root.joinpath(*pure.parts).resolve(strict=must_exist)
            candidate.relative_to(self._root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ResourceNotFound("recurso não encontrado") from exc
        return candidate

    def _id(self, path: Path) -> str:
        return path.relative_to(self._root).as_posix()

    @staticmethod
    def _resource(path: Path, resource_id: str) -> MediaResource:
        content_type = CONTENT_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        try:
            stat = path.stat(); size = stat.st_size; revision = f"{stat.st_mtime_ns:x}-{size:x}"
        except OSError:
            size = None; revision = None
        return MediaResource(resource_id, content_type, size, revision)

    def _image_for_collection(self, path: Path) -> MediaResource | None:
        for name in ("poster.png", "banner.png", "thumbnail.png"):
            image = path / ".previews" / name
            if image.is_file(): return self._resource(image, self._id(image))
        return None

    def _collection_images(self, path: Path):
        preview = path / ".previews"
        poster_path = next((preview / name for name in ("poster.png", "banner.png") if (preview / name).is_file()), None)
        thumb_path = next((preview / name for name in ("thumbnail.png", "banner.png") if (preview / name).is_file()), None)
        return (self._resource(poster_path, self._id(poster_path)) if poster_path else None,
                self._resource(thumb_path, self._id(thumb_path)) if thumb_path else None)

    def _image_for_video(self, path: Path) -> MediaResource | None:
        for suffix in ("_thumbnail.png", "_banner.png", "_poster.png"):
            image = path.parent / ".previews" / f"{path.stem}{suffix}"
            if image.is_file(): return self._resource(image, self._id(image))
        return None

    def _video_images(self, path: Path):
        preview = path.parent / ".previews"
        poster_path = next((preview / f"{path.stem}{suffix}" for suffix in ("_poster.png", "_banner.png") if (preview / f"{path.stem}{suffix}").is_file()), None)
        thumb_path = next((preview / f"{path.stem}{suffix}" for suffix in ("_thumbnail.png", "_banner.png") if (preview / f"{path.stem}{suffix}").is_file()), None)
        return (self._resource(poster_path, self._id(poster_path)) if poster_path else None,
                self._resource(thumb_path, self._id(thumb_path)) if thumb_path else None)

    async def browse(self, parent_id: str | None = None, cursor: str | None = None) -> CatalogPage:
        if cursor is not None:
            raise CollectionNotFound("paginação não suportada")
        try:
            parent = self._resolve(parent_id)
        except ResourceNotFound as exc:
            raise CollectionNotFound("coleção não encontrada") from exc
        if not parent.is_dir():
            raise CollectionNotFound("coleção não encontrada")
        try:
            children = list(parent.iterdir())
        except OSError as exc:
            raise SourceUnavailable("origem temporariamente indisponível") from exc
        collections, playable = [], []
        for child in children:
            if child.name.startswith("."):
                continue
            try:
                resolved = child.resolve(strict=True)
                resolved.relative_to(self._root)
            except (OSError, RuntimeError, ValueError):
                continue
            if resolved.is_dir():
                poster, thumbnail = self._collection_images(resolved)
                collections.append(CatalogEntry(self._id(resolved), child.name, EntryType.COLLECTION,
                                                image=poster or thumbnail, poster=poster, thumbnail=thumbnail,
                                                entity_kind="collection"))
            elif resolved.is_file() and resolved.suffix.lower() in VIDEO_EXTENSIONS:
                poster, thumbnail = self._video_images(resolved)
                playable.append(CatalogEntry(self._id(resolved), child.name, EntryType.PLAYABLE,
                                             "video", thumbnail or poster, poster, thumbnail, "video"))
        key = lambda item: item.title.casefold()
        return CatalogPage(tuple(sorted(collections, key=key) + sorted(playable, key=key)))

    async def search(self, query: str, cursor: str | None = None) -> CatalogPage:
        if cursor is not None:
            raise CollectionNotFound("paginação não suportada")
        needle = query.strip().casefold()
        if not needle:
            return CatalogPage(())
        items = []
        try:
            paths = self._root.rglob("*")
            for path in paths:
                if any(part.startswith(".") for part in path.relative_to(self._root).parts): continue
                if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS and needle in path.name.casefold():
                    poster, thumbnail = self._video_images(path)
                    items.append(CatalogEntry(self._id(path), path.name, EntryType.PLAYABLE, "video", thumbnail or poster, poster, thumbnail, "video"))
        except OSError as exc:
            raise SourceUnavailable("origem temporariamente indisponível") from exc
        return CatalogPage(tuple(sorted(items, key=lambda item: item.title.casefold())))

    @staticmethod
    def _track_metadata(path: Path, stem: str, fallback: str) -> tuple[str, str | None]:
        remainder = path.stem[len(stem):].lstrip("._- ")
        language = remainder.split(".")[-1] if remainder else None
        if language and len(language) > 8:
            language = None
        return ((language or fallback).upper(), language)

    def _sidecars(self, video: Path, folder: str, extensions: set[str]) -> tuple[MediaTrack, ...]:
        sidecar_dir = video.parent / folder
        if not sidecar_dir.is_dir():
            return ()
        prefix = video.stem
        tracks = []
        for path in sorted(sidecar_dir.iterdir(), key=lambda value: value.name.casefold()):
            if not path.is_file() or path.suffix.lower() not in extensions:
                continue
            if not path.stem.startswith(prefix):
                continue
            remainder = path.stem[len(prefix):]
            if not remainder.startswith("."):
                continue
            label, language = self._track_metadata(path, prefix, "dub" if folder == ".dubs" else "sub")
            tracks.append(MediaTrack(self._id(path), label, language))
        return tuple(tracks)

    async def get_item(self, media_id: str) -> MediaItem:
        try:
            path = self._resolve(media_id)
        except ResourceNotFound as exc:
            raise MediaItemNotFound("item não encontrado") from exc
        if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
            raise MediaItemNotFound("item não encontrado")
        return MediaItem(
            id=media_id,
            title=path.name,
            video=self._resource(path, media_id),
            audio_tracks=self._sidecars(path, ".dubs", AUDIO_EXTENSIONS),
            subtitles=self._sidecars(path, ".subs", {".vtt"}),
            image=self._image_for_video(path),
            poster=self._video_images(path)[0],
            thumbnail=self._video_images(path)[1],
        )

    async def open_resource(self, resource_id: str, byte_range: ByteRangeRequest | None = None) -> OpenedResource:
        try:
            path = self._resolve(resource_id)
        except ResourceNotFound:
            raise
        if not path.is_file():
            raise ResourceNotFound("recurso não encontrado")
        relative_parts = path.relative_to(self._root).parts
        extension = path.suffix.lower()
        allowed = (
            extension in VIDEO_EXTENSIONS
            or (".dubs" in relative_parts and extension in AUDIO_EXTENSIONS)
            or (".subs" in relative_parts and extension == ".vtt")
            or (".previews" in relative_parts and extension in {".png", ".jpg", ".jpeg", ".webp"})
        )
        if not allowed:
            raise ResourceNotFound("recurso não encontrado")
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise SourceUnavailable("origem temporariamente indisponível") from exc
        start, end = 0, size - 1
        if byte_range:
            if size == 0:
                raise InvalidByteRange("recurso vazio")
            if byte_range.suffix_length is not None:
                if byte_range.suffix_length <= 0:
                    raise InvalidByteRange("intervalo inválido")
                start = max(0, size - byte_range.suffix_length)
            else:
                start = byte_range.start if byte_range.start is not None else 0
                end = byte_range.end if byte_range.end is not None else size - 1
                if start < 0 or start >= size or end < start:
                    raise InvalidByteRange("intervalo inválido")
                end = min(end, size - 1)

        async def chunks():
            stream = None
            try:
                stream = await asyncio.to_thread(path.open, "rb")
                await asyncio.to_thread(stream.seek, start)
                remaining = end - start + 1
                while remaining:
                    chunk = await asyncio.to_thread(stream.read, min(1024 * 256, remaining))
                    if not chunk:
                        raise SourceReadError("falha ao ler recurso")
                    remaining -= len(chunk)
                    yield chunk
            except SourceReadError:
                raise
            except OSError as exc:
                raise SourceReadError("falha ao ler recurso") from exc
            finally:
                if stream is not None:
                    await asyncio.to_thread(stream.close)

        content_type = CONTENT_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return OpenedResource(chunks(), size, content_type, start, end)
