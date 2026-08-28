from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from playback.models import (OriginPresentation, OriginRepresentation, OriginSegment,
                             OriginTrack, SegmentArtifact, SegmentDemand)
from media_sources.errors import SourceUnavailable


class DirectoryPlaybackAdapter:
    PACKAGER_VERSION = "directory-fmp4-v1"

    def __init__(self, root: Path, ffmpeg_path="ffmpeg.exe", transcode_profile="chrome-h264-aac",
                 hardware_acceleration="auto"):
        self.root, self.ffmpeg = root, ffmpeg_path
        self.profile, self.hardware = transcode_profile, hardware_acceleration
        self.available = shutil.which(ffmpeg_path) is not None

    def _path(self, media_id):
        path = (self.root / Path(media_id)).resolve(strict=True); path.relative_to(self.root)
        return path

    async def inspect(self, media_id):
        if not self.available: raise SourceUnavailable("FFmpeg indisponível para playback")
        path = self._path(media_id)
        probe = str(Path(self.ffmpeg).with_name("ffprobe.exe")) if Path(self.ffmpeg).name.lower() == "ffmpeg.exe" else "ffprobe"
        command = [probe, "-v", "error", "-show_entries", "format=duration:stream=codec_name,codec_type,width,height,bit_rate", "-of", "json", str(path)]
        try:
            result = await asyncio.to_thread(subprocess.run, command, capture_output=True, text=True, timeout=20, check=True)
            info = json.loads(result.stdout); duration = float(info["format"]["duration"])
        except Exception as exc: raise SourceUnavailable("não foi possível inspecionar a mídia local") from exc
        stat = path.stat(); fingerprint = hashlib.sha256(f"{path}|{stat.st_size}|{stat.st_mtime_ns}|{self.PACKAGER_VERSION}|{self.profile}".encode()).hexdigest()
        count = max(1, int((duration + 9.999) // 10)); timeline = tuple(OriginSegment(str(i), i * 10, min(10, duration - i * 10)) for i in range(count))
        tracks = []
        for index, stream in enumerate(info.get("streams", [])):
            kind = stream.get("codec_type")
            if kind not in ("video", "audio"): continue
            rep = OriginRepresentation(f"{kind}-{index}", int(stream.get("bit_rate") or (4_000_000 if kind == "video" else 192_000)),
                "avc1.640028" if kind == "video" else "mp4a.40.2", f"{kind}/mp4", "init", timeline,
                stream.get("width") if kind == "video" else None, stream.get("height") if kind == "video" else None)
            tracks.append(OriginTrack(f"{kind}-{index}", kind, (rep,), default=not any(t.kind == kind for t in tracks)))
        return OriginPresentation(media_id, path.name, duration, tuple(tracks), fingerprint,
            canonical_video_representation=next((t.representations[0].id for t in tracks if t.kind == "video"), None))

    async def materialize(self, media_id, demand: SegmentDemand):
        path = self._path(media_id); start = 0 if demand.segment_identity == "init" else int(demand.segment_identity) * 10
        duration = 10
        handle, name = tempfile.mkstemp(prefix="watchparty-artifact-", suffix=".mp4"); os.close(handle); Path(name).unlink(missing_ok=True)
        output = Path(name); mapping = "0:v:0" if demand.track_id.startswith("video") else "0:a:0"
        command = [self.ffmpeg, "-v", "error", "-ss", str(start), "-i", str(path), "-t", str(duration), "-map", mapping]
        command += ["-c:v", "libx264", "-an"] if mapping.startswith("0:v") else ["-c:a", "aac", "-vn"]
        command += ["-movflags", "+frag_keyframe+empty_moov+default_base_moof", "-f", "mp4", "-y", str(output)]
        try: await asyncio.to_thread(subprocess.run, command, capture_output=True, timeout=60, check=True)
        except Exception as exc: raise SourceUnavailable("falha ao materializar segmento local") from exc
        complete = output.read_bytes()
        init, media = _split_fragmented_mp4(complete)
        data = init if demand.segment_identity == "init" else media
        if not data: raise SourceUnavailable("FFmpeg produziu um fragmento local vazio")
        output.write_bytes(data); digest = hashlib.sha256(data).hexdigest()
        return SegmentArtifact(output, "video/mp4" if mapping.startswith("0:v") else "audio/mp4", len(data), digest)


def _split_fragmented_mp4(data: bytes) -> tuple[bytes, bytes]:
    """Split a single-fragment MP4 into its init and media portions."""
    offset = 0
    media_offset = None
    while offset + 8 <= len(data):
        size = int.from_bytes(data[offset:offset + 4], "big")
        kind = data[offset + 4:offset + 8]
        header = 8
        if size == 1:
            if offset + 16 > len(data): break
            size = int.from_bytes(data[offset + 8:offset + 16], "big"); header = 16
        elif size == 0:
            size = len(data) - offset
        if size < header or offset + size > len(data): break
        if kind in (b"moof", b"styp", b"sidx"):
            media_offset = offset
            break
        offset += size
    if media_offset is None:
        raise SourceUnavailable("FFmpeg não produziu fMP4 fragmentado")
    return data[:media_offset], data[media_offset:]
