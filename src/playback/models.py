from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Protocol

from media_sources.models import MediaResource, OpenedResource


class DemandPriority(IntEnum):
    PLAYBACK = 0
    BUFFER = 1
    CANONICAL = 2


@dataclass(frozen=True)
class OriginSegment:
    identity: str
    start: float
    duration: float


@dataclass(frozen=True)
class OriginRepresentation:
    id: str
    bandwidth: int
    codecs: str
    mime_type: str
    initialization: str
    segments: tuple[OriginSegment, ...]
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class OriginTrack:
    id: str
    kind: str
    representations: tuple[OriginRepresentation, ...]
    language: str | None = None
    label: str | None = None
    default: bool = False


@dataclass(frozen=True)
class OriginPresentation:
    media_id: str
    title: str
    duration: float
    tracks: tuple[OriginTrack, ...]
    revision_seed: str
    image: MediaResource | None = None
    canonical_video_representation: str | None = None


@dataclass(frozen=True)
class SegmentDemand:
    track_id: str
    representation_id: str
    segment_identity: str
    priority: DemandPriority = DemandPriority.PLAYBACK


@dataclass(frozen=True)
class SegmentArtifact:
    path: Path
    content_type: str
    size: int
    sha256: str


@dataclass(frozen=True)
class PlaybackSelection:
    source_id: str
    media_id: str


@dataclass(frozen=True)
class PlaybackDescriptor:
    playback_id: str
    revision: str
    manifest: MediaResource
    title: str
    image: MediaResource | None = None


@dataclass(frozen=True)
class ResourceRequest:
    method: str = "GET"


class PlaybackOrigin(Protocol):
    async def inspect(self, media_id: str) -> OriginPresentation: ...
    async def materialize(self, media_id: str, demand: SegmentDemand) -> SegmentArtifact: ...


class PlaybackError(Exception): pass
class PlaybackNotFound(PlaybackError): pass
class PlaybackExpired(PlaybackError): pass
class PlaybackPaused(PlaybackError): pass
class MaterializationTimeout(PlaybackError): pass
class InvalidPlaybackResource(PlaybackError): pass
