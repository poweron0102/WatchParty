from __future__ import annotations

import asyncio
import hashlib
import math
import shutil
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from playback.models import (OriginPresentation, OriginRepresentation, OriginSegment,
                             OriginTrack, SegmentDemand)
from media_sources.errors import SourceUnavailable
from .encoder import (EncoderChoice, SEGMENT_SECONDS, avc_codec, copy_audio, copy_video,
                      frame_rate, h264_level, probe, video_keyframes, video_options)
from .fragmented_mp4 import _split_fragmented_mp4  # compatibility with existing callers
from .memory import MemorySegments
from .producer import SegmentProducer


@dataclass(frozen=True)
class _Track:
    stream: dict
    kind: str
    representation: OriginRepresentation
    encoder: str
    acceleration: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Media:
    presentation: OriginPresentation
    tracks: dict[str, _Track]
    signature: tuple[int, int]


class DirectoryPlaybackAdapter:
    PACKAGER_VERSION = 'directory-ram-fmp4-v2'

    def __init__(self, root: Path, ffmpeg_path='ffmpeg.exe', transcode_profile='chrome-h264-aac',
                 hardware_acceleration='auto', memory_cache_bytes=256 * 1024 * 1024):
        self.root = Path(root).resolve()
        self.ffmpeg = ffmpeg_path
        self.profile, self.hardware = transcode_profile, hardware_acceleration
        self.available = shutil.which(ffmpeg_path) is not None
        self.cache = MemorySegments(memory_cache_bytes)
        self._encoders = EncoderChoice(ffmpeg_path, hardware_acceleration)
        self._media: OrderedDict[str, _Media] = OrderedDict()
        self._inspection_lock = asyncio.Lock()
        self._lock = asyncio.Lock()
        self._changed = asyncio.Event()
        self._producers: list[tuple[str, str, SegmentProducer]] = []
        self._generations: dict[str, int] = {}
        self._closed = False
        self.max_producers = 2

    def _path(self, media_id):
        path = (self.root / Path(media_id)).resolve(strict=True)
        path.relative_to(self.root)
        return path

    async def inspect(self, media_id):
        if self._closed:
            raise SourceUnavailable('origem local encerrada')
        if not self.available:
            raise SourceUnavailable('FFmpeg indisponível para playback')
        async with self._inspection_lock:
            path = self._path(media_id)
            stat = path.stat()
            signature = stat.st_size, stat.st_mtime_ns
            existing = self._media.get(media_id)
            if existing and existing.signature == signature:
                self._media.move_to_end(media_id)
                return existing.presentation
            if existing:
                await self.release(media_id)
            info = await probe(self.ffmpeg, path)
            duration = float(info['format']['duration'])
            tracks, plans = [], {}
            for stream in info.get('streams', []):
                kind = stream.get('codec_type')
                if kind not in ('video', 'audio') or stream.get('disposition', {}).get('attached_pic'):
                    continue
                acceleration = ()
                if kind == 'video':
                    if copy_video(stream):
                        try:
                            starts = await video_keyframes(self.ffmpeg, path, stream, duration)
                            codecs = await avc_codec(self.ffmpeg, path, stream)
                            encoder = 'copy'
                        except SourceUnavailable:
                            encoder = None
                    else:
                        encoder = None
                    if encoder is None:
                        encoder, acceleration = await self._encoders.choose(path, stream)
                        rate = frame_rate(stream)
                        step = math.ceil(float(rate) * SEGMENT_SECONDS) / float(rate)
                        starts = [i * step for i in range(math.ceil(duration / step))]
                        codecs = f'avc1.6400{h264_level(stream):02x}'
                else:
                    encoder = 'copy' if copy_audio(stream) else 'aac'
                    sample_rate = int(stream['sample_rate']) if encoder == 'copy' else 48000
                    step = math.ceil(SEGMENT_SECONDS * sample_rate / 1024) * 1024 / sample_rate
                    starts = [i * step for i in range(math.ceil(duration / step))]
                    codecs = 'mp4a.40.2'
                timeline = tuple(OriginSegment(str(i), start,
                    (starts[i + 1] if i + 1 < len(starts) else duration) - start)
                    for i, start in enumerate(starts))
                track_id = f"{kind}-{stream['index']}"
                rep = OriginRepresentation(track_id, int(stream.get('bit_rate') or
                    (4_000_000 if kind == 'video' else 192_000)), codecs, f'{kind}/mp4',
                    'init', timeline, stream.get('width'), stream.get('height'))
                tags = stream.get('tags', {})
                tracks.append(OriginTrack(track_id, kind, (rep,), tags.get('language'), tags.get('title'),
                                          not any(t.kind == kind for t in tracks)))
                plans[track_id] = _Track(stream, kind, rep, encoder, acceleration)
            if not tracks:
                raise SourceUnavailable('mídia sem áudio ou vídeo reproduzível')
            fingerprint = hashlib.sha256(f'{path}|{signature}|{self.PACKAGER_VERSION}|{self.profile}|{self.hardware}'.encode()).hexdigest()
            # Local sources have no archival/canonical rendition to prefetch.
            presentation = OriginPresentation(media_id, path.name, duration, tuple(tracks), fingerprint)
            self._media[media_id] = _Media(presentation, plans, signature)
            while len(self._media) > 16:
                oldest = next(iter(self._media))
                await self.release(oldest)
                self._media.pop(oldest)
            return presentation

    def _cache_key(self, media_id, track_id, identity):
        media = self._media.get(media_id)
        if media is None:
            return None
        return media_id, media.presentation.revision_seed, track_id, identity

    def locate(self, media_id, demand):
        if demand.representation_id != demand.track_id:
            return None
        return self.cache.get(self._cache_key(media_id, demand.track_id, demand.segment_identity))

    def _command(self, media_id, track, start_index):
        start = track.representation.segments[start_index].start
        command = [self.ffmpeg, '-nostdin', '-v', 'error', '-threads', '2', *track.acceleration,
                   '-ss', f'{start:.9f}', '-i', str(self._path(media_id)),
                   '-map', f"0:{track.stream['index']}", '-map_metadata', '-1']
        if track.kind == 'video':
            command += ['-an', '-sn', '-dn']
            if track.encoder == 'copy':
                command += ['-c:v', 'copy']
            else:
                command += video_options(track.encoder, track.stream)
            flags = '+frag_keyframe+empty_moov+default_base_moof+negative_cts_offsets'
        else:
            command += ['-vn', '-sn', '-dn', '-c:a', track.encoder]
            if track.encoder != 'copy':
                command += ['-ar', '48000', '-b:a', '192k',
                            '-af', 'aresample=async=1:first_pts=0']
            flags = '+empty_moov+default_base_moof'
            command += ['-frag_duration', str(SEGMENT_SECONDS * 1_000_000)]
        return command + ['-movflags', flags, '-flush_packets', '1', '-f', 'mp4', 'pipe:1']

    async def materialize(self, media_id, demand: SegmentDemand):
        if media_id not in self._media:
            await self.inspect(media_id)
        media = self._media[media_id]
        generation = self._generations.get(media_id, 0)
        track = media.tracks.get(demand.track_id)
        identity = demand.segment_identity
        if track is None or demand.representation_id != track.representation.id:
            raise SourceUnavailable('faixa local inválida')
        if identity != 'init' and (not identity.isdecimal() or int(identity) >= len(track.representation.segments)):
            raise SourceUnavailable('segmento local inválido')
        while True:
            async with self._lock:
                if self._closed or self._generations.get(media_id, 0) != generation:
                    raise SourceUnavailable('origem local encerrada')
                ready = self.locate(media_id, demand)
                if ready:
                    return ready
                self._producers = [(m, t, p) for m, t, p in self._producers if not p.closed]
                producer = next((p for m, t, p in self._producers
                    if m == media_id and t == demand.track_id and p.can_serve(identity)), None)
                if producer is None:
                    if len(self._producers) >= self.max_producers:
                        idle = next(((m, t, p) for m, t, p in self._producers if not p.pending), None)
                        if idle:
                            await idle[2].aclose()
                            self._producers.remove(idle)
                    if len(self._producers) < self.max_producers:
                        start = 0 if identity == 'init' else int(identity)
                        cache_prefix = (media_id, media.presentation.revision_seed, demand.track_id)
                        def publish(segment_id, artifact, prefix=cache_prefix):
                            self.cache.put((*prefix, segment_id), artifact)
                        producer = SegmentProducer(self._command(media_id, track, start), track, start,
                                                   publish, self._changed)
                        self._producers.append((media_id, demand.track_id, producer))
                if producer:
                    future = producer.request(identity)
                    break
                self._changed.clear()
            await self._changed.wait()
        return await asyncio.shield(future)

    async def release(self, media_id):
        async with self._lock:
            self._generations[media_id] = self._generations.get(media_id, 0) + 1
            closing = [p for m, _, p in self._producers if m == media_id]
            await asyncio.gather(*(p.aclose() for p in closing))
            self._producers = [(m, t, p) for m, t, p in self._producers if m != media_id]
            self._changed.set()

    async def aclose(self):
        async with self._lock:
            self._closed = True
            await asyncio.gather(*(p.aclose() for _, _, p in self._producers))
            self._producers.clear()
            self.cache.clear()
            self._changed.set()
