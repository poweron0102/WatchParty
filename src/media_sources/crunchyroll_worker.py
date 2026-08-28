from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from pathlib import Path

from playback.models import (OriginPresentation, OriginRepresentation, OriginSegment,
                             OriginTrack, SegmentArtifact, SegmentDemand)
from .errors import SourceUnavailable


class CrunchyrollWorkerClient:
    """Versioned JSON-Lines client. Secrets are sent only through stdin."""
    VERSION = 1

    def __init__(self, worker_path, cookie, options):
        self.path, self.cookie, self.options = str(worker_path), cookie, options
        self._process = None; self._pending = {}; self._reader = None; self._write_lock = asyncio.Lock()

    async def _start(self):
        if self._process and self._process.returncode is None: return
        try:
            self._process = await asyncio.create_subprocess_exec(self.path, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        except OSError as exc: raise SourceUnavailable("worker de playback indisponível") from exc
        self._reader = asyncio.create_task(self._read())
        await self.command("activate", {"etp_rt": self.cookie, "options": self.options})

    async def _read(self):
        while self._process and (line := await self._process.stdout.readline()):
            try: message = json.loads(line)
            except ValueError: continue
            request_id = message.get("request_id"); future = self._pending.get(request_id)
            if not future: continue
            if message.get("event") == "failed": future.set_exception(SourceUnavailable("worker não pôde materializar o recurso"))
            elif message.get("event") in ("completed", "asset", "released"): future.set_result(message)

    async def command(self, name, payload):
        if name != "activate": await self._start()
        request_id = uuid.uuid4().hex; future = asyncio.get_running_loop().create_future(); self._pending[request_id] = future
        message = {"version": self.VERSION, "command": name, "request_id": request_id, "correlation_id": uuid.uuid4().hex, **payload}
        try:
            async with self._write_lock:
                self._process.stdin.write((json.dumps(message, separators=(",", ":")) + "\n").encode()); await self._process.stdin.drain()
            return await future
        finally: self._pending.pop(request_id, None)

    async def inspect(self, media_id):
        result = await self.command("inspect_version", {"media_key": media_id})
        data = result["presentation"]; tracks = []
        for raw_track in data["tracks"]:
            reps = []
            for raw_rep in raw_track["representations"]:
                segments = tuple(OriginSegment(str(s["identity"]), float(s["start"]), float(s["duration"])) for s in raw_rep["segments"])
                reps.append(OriginRepresentation(str(raw_rep["id"]), int(raw_rep["bandwidth"]), raw_rep["codecs"], raw_rep["mime_type"], str(raw_rep["initialization"]), segments, raw_rep.get("width"), raw_rep.get("height")))
            tracks.append(OriginTrack(str(raw_track["id"]), raw_track["kind"], tuple(reps), raw_track.get("language"), raw_track.get("label"), raw_track.get("default", False)))
        return OriginPresentation(media_id, data["title"], float(data["duration"]), tuple(tracks), data["revision_seed"], canonical_video_representation=data.get("canonical_video_representation"))

    async def materialize(self, media_id, demand: SegmentDemand):
        result = await self.command("materialize", {"media_key": media_id, "demand": {
            "track_id": demand.track_id, "representation_id": demand.representation_id,
            "segment_identity": demand.segment_identity, "priority": int(demand.priority)}})
        path = Path(result["path"]); data = await asyncio.to_thread(path.read_bytes); digest = hashlib.sha256(data).hexdigest()
        if result.get("sha256") != digest: raise SourceUnavailable("worker retornou artefato inválido")
        return SegmentArtifact(path, result["content_type"], len(data), digest)
