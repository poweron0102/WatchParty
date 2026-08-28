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
from .errors import SourceUnavailable


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
        duration = 0.05 if demand.segment_identity == "init" else 10
        handle, name = tempfile.mkstemp(prefix="watchparty-artifact-", suffix=".mp4"); os.close(handle); Path(name).unlink(missing_ok=True)
        output = Path(name); mapping = "0:v:0" if demand.track_id.startswith("video") else "0:a:0"
        command = [self.ffmpeg, "-v", "error", "-ss", str(start), "-i", str(path), "-t", str(duration), "-map", mapping]
        command += ["-c:v", "libx264", "-an"] if mapping.startswith("0:v") else ["-c:a", "aac", "-vn"]
        command += ["-movflags", "+frag_keyframe+empty_moov+default_base_moof", "-f", "mp4", "-y", str(output)]
        try: await asyncio.to_thread(subprocess.run, command, capture_output=True, timeout=60, check=True)
        except Exception as exc: raise SourceUnavailable("falha ao materializar segmento local") from exc
        data = output.read_bytes(); digest = hashlib.sha256(data).hexdigest()
        return SegmentArtifact(output, "video/mp4" if mapping.startswith("0:v") else "audio/mp4", len(data), digest)
