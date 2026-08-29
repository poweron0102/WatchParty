from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
import uuid
from pathlib import Path

from playback.models import (OriginPresentation, OriginRepresentation, OriginSegment,
                             OriginTrack, SegmentArtifact, SegmentDemand)
from media_sources.errors import SourceUnavailable


class CrunchyrollWorkerClient:
    """Versioned JSON-Lines client. Secrets are sent only through stdin."""
    VERSION = 1
    STREAM_LIMIT = 16 * 1024 * 1024

    def __init__(self, worker_path, cookie, options):
        self.path, self.cookie, self.options = str(worker_path), cookie, options
        self._process = None; self._pending = {}; self._reader = None; self._write_lock = asyncio.Lock()
        self._pending_context = {}
        self._start_lock = asyncio.Lock()

    def _safe_diagnostic(self, message):
        safe = str(message or "falha sem detalhes")
        for value in (self.cookie, self.options.get("cache_path"), self.options.get("client_id_path"),
                      self.options.get("private_key_path"), self.options.get("widevine_device_path")):
            if value: safe = safe.replace(str(value), "<redacted>")
        return re.sub(r"https?://\S+", "<url>", safe)[:240]

    async def _start(self):
        async with self._start_lock:
            if self._process and self._process.returncode is None: return
            try:
                self._process = await asyncio.create_subprocess_exec(self.path, stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=self.STREAM_LIMIT)
            except OSError as exc: raise SourceUnavailable("worker de playback indisponível") from exc
            self._reader = asyncio.create_task(self._read())
            asyncio.create_task(self._read_stderr())
            await self.command("activate", {"etp_rt": self.cookie, "options": self.options})

    async def _read_stderr(self):
        process = self._process
        if not process or not process.stderr:
            return
        while line := await process.stderr.readline():
            print(f"Crunchyroll worker stderr: {self._safe_diagnostic(line.decode(errors='replace').rstrip())}", file=sys.stderr)

    async def _read(self):
        while self._process and (line := await self._process.stdout.readline()):
            try: message = json.loads(line)
            except ValueError: continue
            request_id = message.get("request_id"); future = self._pending.get(request_id)
            if not future: continue
            if message.get("event") == "failed":
                code = message.get("code", "worker_failed")
                print(f"Crunchyroll worker [{code}]: {self._safe_diagnostic(message.get('message'))}", file=sys.stderr)
                future.set_exception(SourceUnavailable("worker não pôde materializar o recurso"))
            elif message.get("event") == "stage":
                context = self._pending_context.get(request_id, "")
                suffix = f" {context}" if context else ""
                print(f"Crunchyroll worker: {message.get('stage', 'working')}{suffix}", file=sys.stderr)
            elif message.get("event") in ("completed", "asset", "released"): future.set_result(message)
        for future in tuple(self._pending.values()):
            if not future.done(): future.set_exception(SourceUnavailable("worker de playback foi encerrado"))

    async def command(self, name, payload):
        if name != "activate": await self._start()
        request_id = uuid.uuid4().hex; future = asyncio.get_running_loop().create_future(); self._pending[request_id] = future
        demand = payload.get("demand") or {}
        priority = {0: "playback", 1: "buffer", 2: "canonical"}.get(demand.get("priority"), demand.get("priority"))
        fields = [("command", name), ("media", payload.get("media_key")),
                  ("track", demand.get("track_id")), ("representation", demand.get("representation_id")),
                  ("segment", demand.get("segment_identity")), ("priority", priority)]
        safe = lambda value: re.sub(r"[\s\x00-\x1f]+", "_", str(value))[:160]
        self._pending_context[request_id] = " ".join(
            f"{key}={safe(value)}" for key, value in fields if value is not None)
        message = {"version": self.VERSION, "command": name, "request_id": request_id, "correlation_id": uuid.uuid4().hex, **payload}
        try:
            async with self._write_lock:
                self._process.stdin.write((json.dumps(message, separators=(",", ":")) + "\n").encode()); await self._process.stdin.drain()
            return await future
        finally:
            self._pending.pop(request_id, None)
            self._pending_context.pop(request_id, None)

    async def inspect(self, media_id):
        result = await self.command("inspect_version", {"media_key": media_id})
        data = result["presentation"]; tracks = []
        for raw_track in data["tracks"]:
            reps = []
            for raw_rep in raw_track["representations"]:
                segments = tuple(OriginSegment(str(s["identity"]), float(s["start"]), float(s["duration"])) for s in (raw_rep.get("segments") or ()))
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
