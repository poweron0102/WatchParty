from __future__ import annotations

import asyncio
import hashlib
import secrets
from dataclasses import dataclass
from pathlib import Path

from media_sources.models import MediaResource, OpenedResource
from .manifest import build_mpd
from .models import (DemandPriority, InvalidPlaybackResource, MaterializationTimeout, PlaybackDescriptor,
                     PlaybackExpired, PlaybackNotFound, PlaybackOrigin, PlaybackPaused,
                     PlaybackSelection, ResourceRequest, SegmentDemand)
from .scheduler import MaterializationPlanner
from .store import SegmentStore


@dataclass
class _Active:
    descriptor: PlaybackDescriptor
    selection: PlaybackSelection
    origin: PlaybackOrigin
    presentation: object
    manifest: bytes
    resources: dict[str, SegmentDemand]
    paused: bool = False


class PlaybackModule:
    def __init__(self, origins: dict[str, PlaybackOrigin], cache_path: str | Path = "cache/playback",
                 max_segment_downloads: int = 4, wait_timeout: float = 30):
        self._origins = origins
        self._store = SegmentStore(cache_path)
        self._planner = MaterializationPlanner(self._store, max_segment_downloads)
        self._timeout = wait_timeout
        self._active: _Active | None = None
        self._expired: set[str] = set()
        self._background: set[asyncio.Task] = set()
        self._lock = asyncio.Lock()

    async def select(self, selection: PlaybackSelection) -> PlaybackDescriptor:
        try: origin = self._origins[selection.source_id]
        except KeyError as exc: raise PlaybackNotFound("origem não encontrada") from exc
        presentation = await origin.inspect(selection.media_id)
        revision = hashlib.sha256((selection.source_id + "\0" + presentation.revision_seed).encode()).hexdigest()[:24]
        async with self._lock:
            if self._active and self._active.selection == selection and self._active.descriptor.revision == revision:
                return self._active.descriptor
            if self._active: self._expired.add(self._active.descriptor.playback_id)
            playback_id = secrets.token_urlsafe(18)
            resources, urls = {}, {}
            for track in presentation.tracks:
                for rep in track.representations:
                    for identity in (rep.initialization, *(segment.identity for segment in rep.segments)):
                        opaque = secrets.token_urlsafe(18)
                        resources[opaque] = SegmentDemand(track.id, rep.id, identity)
                        urls[(track.id, rep.id, identity)] = f'/playback/{playback_id}/asset/{opaque}'
            manifest = build_mpd(presentation, urls)
            descriptor = PlaybackDescriptor(playback_id, revision,
                MediaResource("manifest.mpd", "application/dash+xml", len(manifest)), presentation.title, presentation.image)
            self._active = _Active(descriptor, selection, origin, presentation, manifest, resources)
            return descriptor

    async def set_download_paused(self, playback_id: str, paused: bool) -> None:
        active = self._require(playback_id); active.paused = paused

    def _require(self, playback_id: str) -> _Active:
        if playback_id in self._expired: raise PlaybackExpired("apresentação substituída")
        if not self._active or self._active.descriptor.playback_id != playback_id: raise PlaybackNotFound("apresentação não encontrada")
        return self._active

    async def open(self, playback_id: str, resource_id: str, request: ResourceRequest) -> OpenedResource:
        active = self._require(playback_id)
        if resource_id == "manifest.mpd": return _opened(active.manifest, "application/dash+xml")
        try: demand = active.resources[resource_id]
        except KeyError as exc: raise InvalidPlaybackResource("recurso não declarado") from exc
        ready = self._store.locate(active.selection.media_id, demand)
        if active.paused and not ready: raise PlaybackPaused("materialização pausada")
        try:
            artifact = ready or await asyncio.wait_for(self._planner.materialize(
                active.selection.media_id, demand,
                lambda: active.origin.materialize(active.selection.media_id, demand)), self._timeout)
        except TimeoutError as exc: raise MaterializationTimeout("tempo de materialização esgotado") from exc
        data = await asyncio.to_thread(artifact.path.read_bytes)
        mirror = self._canonical_demand(active, demand)
        if mirror and not self._store.locate(active.selection.media_id, mirror):
            task = asyncio.create_task(self._planner.materialize(active.selection.media_id, mirror,
                lambda: active.origin.materialize(active.selection.media_id, mirror)))
            self._background.add(task); task.add_done_callback(self._background.discard)
        return _opened(data, artifact.content_type)

    @staticmethod
    def _canonical_demand(active: _Active, demand: SegmentDemand) -> SegmentDemand | None:
        canonical = active.presentation.canonical_video_representation
        if not canonical or demand.representation_id == canonical: return None
        source_segment = None
        for track in active.presentation.tracks:
            for rep in track.representations:
                if track.id == demand.track_id and rep.id == demand.representation_id:
                    source_segment = next((s for s in rep.segments if s.identity == demand.segment_identity), None)
        if not source_segment: return None
        for track in active.presentation.tracks:
            if track.kind != "video": continue
            for rep in track.representations:
                if rep.id != canonical: continue
                target = next((s for s in rep.segments if s.start < source_segment.start + source_segment.duration and
                               source_segment.start < s.start + s.duration), None)
                if target: return SegmentDemand(track.id, rep.id, target.identity, DemandPriority.CANONICAL)
        return None


def _opened(data: bytes, content_type: str) -> OpenedResource:
    async def chunks():
        if data: yield data
    return OpenedResource(chunks(), len(data), content_type, 0, max(0, len(data) - 1))
