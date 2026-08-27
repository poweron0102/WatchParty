from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import AsyncIterator, Protocol


class EntryType(str, Enum):
    COLLECTION = "collection"
    PLAYABLE = "playable"


@dataclass(frozen=True)
class MediaResource:
    id: str
    content_type: str
    size: int | None = None


@dataclass(frozen=True)
class SourceSummary:
    id: str
    label: str
    capabilities: tuple[str, ...] = ("browse", "stream")


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    title: str
    entry_type: EntryType
    media_kind: str | None = None
    image: MediaResource | None = None


@dataclass(frozen=True)
class CatalogPage:
    items: tuple[CatalogEntry, ...]
    next_cursor: str | None = None


@dataclass(frozen=True)
class MediaTrack:
    resource_id: str
    label: str
    language: str | None = None
    default: bool = False


@dataclass(frozen=True)
class MediaItem:
    id: str
    title: str
    video: MediaResource
    audio_tracks: tuple[MediaTrack, ...] = ()
    subtitles: tuple[MediaTrack, ...] = ()
    image: MediaResource | None = None


@dataclass(frozen=True)
class ByteRangeRequest:
    start: int | None = None
    end: int | None = None
    suffix_length: int | None = None


@dataclass(frozen=True)
class OpenedResource:
    chunks: AsyncIterator[bytes]
    total_size: int
    content_type: str
    start: int
    end: int

    @property
    def content_length(self) -> int:
        return self.end - self.start + 1


class MediaSource(Protocol):
    async def browse(self, parent_id: str | None = None, cursor: str | None = None) -> CatalogPage: ...
    async def get_item(self, media_id: str) -> MediaItem: ...
    async def open_resource(self, resource_id: str, byte_range: ByteRangeRequest | None = None) -> OpenedResource: ...
