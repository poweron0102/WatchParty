from __future__ import annotations

import asyncio
import hashlib
import heapq
import itertools
import json
import os
import re
import secrets
import shutil
import sys
from dataclasses import asdict, replace
from pathlib import Path

from fastapi import HTTPException

from media_sources.models import CatalogEntry, CatalogPage, EntryType, MediaItem, MediaResource
from playback.models import (DemandPriority, OriginPresentation, OriginRepresentation, OriginTrack,
                             SegmentArtifact, SegmentDemand)

from .cache import CrunchyrollCache
from .catalog_core import CrunchyrollSource
from .jobs import TransientJobs


class _PriorityGate:
    def __init__(self, limit: int):
        self.limit = limit; self.active = 0; self.waiting = []; self.lock = asyncio.Lock(); self.sequence = itertools.count()

    async def acquire(self, priority: int):
        async with self.lock:
            if self.active < self.limit and not self.waiting:
                self.active += 1; return
            future = asyncio.get_running_loop().create_future()
            heapq.heappush(self.waiting, (priority, next(self.sequence), future))
        try: await future
        except BaseException:
            granted = future.done() and not future.cancelled()
            async with self.lock:
                if not future.done(): future.cancel()
            if granted: await self.release()
            raise

    async def release(self):
        async with self.lock:
            while self.waiting:
                _, _, future = heapq.heappop(self.waiting)
                if not future.done(): future.set_result(None); return
            self.active -= 1

    def slot(self, priority: int):
        gate = self
        class Slot:
            async def __aenter__(self): await gate.acquire(priority)
            async def __aexit__(self, *_): await gate.release()
        return Slot()


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024): value.update(chunk)
    return value.hexdigest()


def _safe_name(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return value[:180] or "media"


def _subtitle_to_vtt(raw: bytes, extension: str) -> bytes:
    text = raw.decode("utf-8-sig", errors="replace").replace("\r\n", "\n")
    if extension == ".vtt" or text.lstrip().startswith("WEBVTT"):
        return text.encode("utf-8") if text.lstrip().startswith("WEBVTT") else ("WEBVTT\n\n" + text).encode("utf-8")
    if extension == ".srt":
        converted = re.sub(r"(?m)(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", text)
        return ("WEBVTT\n\n" + converted.strip() + "\n").encode("utf-8")
    if extension == ".ass":
        cues = []
        for line in text.splitlines():
            if not line.startswith("Dialogue:"): continue
            fields = line[len("Dialogue:"):].strip().split(",", 9)
            if len(fields) != 10: continue
            def timestamp(value):
                parts = value.strip().split(":")
                if len(parts) != 3: return value
                return f"{int(parts[0]):02d}:{parts[1]}:{float(parts[2]):06.3f}"
            body = re.sub(r"\{[^}]*\}", "", fields[9]).replace(r"\N", "\n").replace(r"\n", "\n")
            cues.append(f"{timestamp(fields[1])} --> {timestamp(fields[2])}\n{body}")
        return ("WEBVTT\n\n" + "\n\n".join(cues) + "\n").encode("utf-8")
    raise HTTPException(422, "Formato de legenda não suportado")


class ManagedCrunchyrollSource(CrunchyrollSource):
    owns_cache = True

    def __init__(self, source_id, cache_path, etp_rt, locale, metadata_ttl_hours, *, worker_path, worker_options):
        super().__init__(cache_path, etp_rt, locale, metadata_ttl_hours, worker_path=worker_path, worker_options=worker_options)
        self.source_id = source_id
        self.options = dict(worker_options)
        self.cache = CrunchyrollCache(cache_path, source_id)
        self.jobs = TransientJobs()
        self._titles: dict[str, str] = {}
        self._max_downloads = int(worker_options.get("max_segment_downloads", 4))
        self._download_slots = _PriorityGate(self._max_downloads)
        export_path = worker_options.get("export_path") or str(Path(cache_path) / "exports")
        self.export_path = Path(export_path); self.export_path.mkdir(parents=True, exist_ok=True)
        self.ffmpeg = str(worker_options.get("ffmpeg_path", "ffmpeg.exe"))

    async def get_item(self, media_id: str) -> MediaItem:
        item = await super().get_item(media_id); self._titles[media_id] = item.title
        self.cache.update_title(media_id, item.title)
        return item

    async def browse(self, parent_id=None, cursor=None):
        page = await super().browse(parent_id, cursor)
        await asyncio.to_thread(self.cache.remember_catalog, parent_id, page.items, self._image_urls)
        return page

    def _catalog_resource(self, value):
        if not value:
            return None
        try:
            data = json.loads(value) if isinstance(value, str) else value
        except (TypeError, ValueError):
            return None
        if not isinstance(data, dict) or not data.get("id"):
            return None
        if data.get("url"):
            self._image_urls[data["id"]] = data["url"]
        return MediaResource(data["id"], data.get("content_type") or "image/jpeg",
                             data.get("size"), data.get("revision"))

    def _catalog_entry(self, row):
        kind = row.get("entity_kind") or (row["child_id"].split(":", 1)[0]
                                           if ":" in row["child_id"] else "video")
        return CatalogEntry(
            row["child_id"], row["title"],
            EntryType(row["entry_type"]),
            "video" if row["entry_type"] == EntryType.PLAYABLE.value else None,
            self._catalog_resource(row.get("image")),
            poster=self._catalog_resource(row.get("poster")),
            thumbnail=self._catalog_resource(row.get("thumbnail")),
            entity_kind=kind,
        )

    async def _hydrate_catalog_entry(self, row):
        entry = self._catalog_entry(row)
        if entry.image or entry.poster or entry.thumbnail:
            return entry
        try:
            remote = await super().get_entity(row["child_id"])
        except Exception:
            return entry
        await asyncio.to_thread(self.cache.update_catalog_images, row["child_id"],
                                remote.image, remote.poster, remote.thumbnail, self._image_urls)
        return CatalogEntry(
            entry.id, entry.title, entry.entry_type, entry.media_kind,
            remote.image, poster=remote.poster, thumbnail=remote.thumbnail,
            entity_kind=entry.entity_kind)

    async def browse_view(self, view, parent_id=None, cursor=None):
        if view != "cache-local":
            root = {"popular": "popular", "new": "new", "az": "az", "genres": "genres"}.get(view)
            if root and parent_id is None:
                parent_id = f"root:{root}"
        if view != "cache-local":
            return await self.browse(parent_id, cursor)

        inventory = await asyncio.to_thread(self.cache.inventory)
        cached = {row["media_id"]: row for row in inventory if row["state"] != "empty"}
        with self.cache._connect() as db:
            edges = [dict(row) for row in db.execute("SELECT * FROM catalog_edges")]
        by_parent = {}
        by_child = {}
        for edge in edges:
            by_parent.setdefault(edge["parent_id"], []).append(edge)
            by_child.setdefault(edge["child_id"], []).append(edge)

        def has_cached_descendant(node, seen=None):
            seen = seen or set()
            if node in seen: return False
            seen.add(node)
            return any(edge["child_id"] in cached or has_cached_descendant(edge["child_id"], seen)
                       for edge in by_parent.get(node, []))

        items = []
        if parent_id == "cache-group:ungrouped":
            known_children = {edge["child_id"] for edge in edges}
            visible = {media_id: row for media_id, row in cached.items() if media_id not in known_children}
        elif parent_id:
            visible = {edge["child_id"]: cached[edge["child_id"]] for edge in by_parent.get(parent_id, [])
                       if edge["child_id"] in cached}
        else:
            top_ids = {edge["child_id"] for edge in edges
                       if edge["parent_id"].startswith("root:") or edge["parent_id"] == "__root__"}
            visible = {media_id: row for media_id, row in cached.items()
                       if media_id not in {edge["child_id"] for edge in edges} or media_id in top_ids}
        for media_id, row in visible.items():
            kind = media_id.split(":", 1)[0] if ":" in media_id else "video"
            if kind in {"episode", "movie", "video"}:
                edge = {**{"child_id": media_id, "title": row["title"],
                          "entry_type": EntryType.PLAYABLE.value, "entity_kind": kind},
                        **by_child.get(media_id, [{}])[0]}
                entry = await self._hydrate_catalog_entry(edge)
                items.append(CatalogEntry(media_id, row["title"], EntryType.PLAYABLE, "video",
                                          entry.image, poster=entry.poster, thumbnail=entry.thumbnail,
                                          entity_kind=kind))

        collections = {}
        candidates = by_parent.get(parent_id, []) if parent_id and parent_id != "cache-group:ungrouped" else edges
        if parent_id is None:
            candidates = [edge for edge in edges if edge["parent_id"].startswith("root:")]
        for edge in candidates:
            child = edge["child_id"]
            if edge["entry_type"] == EntryType.COLLECTION.value and has_cached_descendant(child):
                collections[child] = await self._hydrate_catalog_entry(edge)
        if parent_id is None and any(media_id not in {edge["child_id"] for edge in edges} for media_id in cached):
            collections["cache-group:ungrouped"] = CatalogEntry("cache-group:ungrouped", "Sem agrupamento",
                                                                 EntryType.COLLECTION, entity_kind="group")
        return CatalogPage(tuple(sorted((*collections.values(), *items), key=lambda item: item.title.casefold())))

    async def inspect(self, media_id):
        presentation = await asyncio.to_thread(self.cache.load_presentation, media_id)
        if presentation is None:
            print(f"Crunchyroll cache: presentation_miss media={media_id}", file=sys.stderr)
            presentation = await super().inspect(media_id)
            presentation = replace(presentation, media_id=media_id, title=self._titles.get(media_id, presentation.title))
            self.cache.remember(presentation, self._titles.get(media_id))
        else:
            print(f"Crunchyroll cache: presentation_hit media={media_id}", file=sys.stderr)
        # Local subtitle attachments alter the host manifest, but never the
        # remote media revision that owns the downloaded audio/video blobs.
        extra = []
        for attachment in self.cache.attachments_for(media_id):
            track_id = f"subtitle:local:{attachment['id']}"; rep_id = f"{track_id}:vtt"
            representation = OriginRepresentation(rep_id, 1, "wvtt", "text/vtt", f"attachment:{attachment['id']}", ())
            extra.append(OriginTrack(track_id, "text", (representation,), attachment["language"], attachment["label"]))
        if extra: presentation = replace(presentation, tracks=(*presentation.tracks, *extra), revision_seed=presentation.revision_seed + ":attachments:" + ":".join(x.id for x in extra))
        return presentation

    def _attachment_artifact(self, media_id: str, demand: SegmentDemand):
        if not demand.segment_identity.startswith("attachment:"): return None
        attachment_id = demand.segment_identity.split(":", 1)[1]
        found = next((item for item in self.cache.attachments_for(media_id) if item["id"] == attachment_id), None)
        if not found: return None
        path = Path(found["vtt_path"])
        if not path.is_file(): return None
        return SegmentArtifact(path, "text/vtt", path.stat().st_size, _digest(path))

    def locate(self, media_id, demand):
        artifact = self._attachment_artifact(media_id, demand) or self.cache.locate(media_id, demand)
        clean = lambda value: re.sub(r"[\s\x00-\x1f]+", "_", str(value))[:160]
        context = (f"media={clean(media_id)} track={clean(demand.track_id)} "
                   f"representation={clean(demand.representation_id)} segment={clean(demand.segment_identity)} "
                   f"priority={demand.priority.name.lower()}")
        print(f"Crunchyroll cache: {'hit' if artifact else 'miss'} {context}", file=sys.stderr)
        return artifact

    async def materialize(self, media_id, demand):
        existing = self.locate(media_id, demand)
        if existing: return existing
        attachment = self._attachment_artifact(media_id, demand)
        if attachment: return attachment
        async with self._download_slots.slot(int(demand.priority)):
            artifact = await super().materialize(media_id, demand)
        return await asyncio.to_thread(self.cache.publish, media_id, demand, artifact)

    @staticmethod
    def _presentation_data(presentation: OriginPresentation):
        return {"media_id": presentation.media_id, "title": presentation.title, "duration": presentation.duration,
                "revision": presentation.revision_seed, "canonical_video_representation": presentation.canonical_video_representation,
                "tracks": [asdict(track) for track in presentation.tracks]}

    def _selected_representations(self, presentation, payload):
        requested_video = payload.get("video_representation") or presentation.canonical_video_representation
        requested_audio = set(payload.get("audio_tracks") or ())
        requested_text = set(payload.get("subtitle_tracks") or ())
        selected = []
        for track in presentation.tracks:
            if track.kind == "video":
                rep = next((value for value in track.representations if value.id == requested_video), None)
                if rep: selected.append((track, rep))
            elif track.kind == "audio" and (track.id in requested_audio or (not requested_audio and track.default)):
                if track.representations: selected.append((track, track.representations[-1]))
            elif track.kind == "text" and track.id in requested_text:
                if track.representations: selected.append((track, track.representations[0]))
        if not any(track.kind == "audio" for track, _ in selected):
            first_audio = next(((track, track.representations[-1]) for track in presentation.tracks if track.kind == "audio" and track.representations), None)
            if first_audio: selected.append(first_audio)
        if not any(track.kind == "video" for track, _ in selected):
            raise ValueError("nenhuma qualidade de vídeo foi selecionada")
        return selected

    @staticmethod
    def _demands(selected):
        result = []
        for track, rep in selected:
            result.append(SegmentDemand(track.id, rep.id, rep.initialization, DemandPriority.BUFFER))
            result.extend(SegmentDemand(track.id, rep.id, segment.identity, DemandPriority.BUFFER) for segment in rep.segments)
        return result

    async def _complete(self, job, media_id, payload, priority=DemandPriority.BUFFER):
        presentation = await self.inspect(media_id); selected = self._selected_representations(presentation, payload)
        demands = self._demands(selected); job.progress(0, len(demands), "Materializando segmentos")
        missing = [demand for demand in demands if not self.locate(media_id, demand)]
        already = len(demands) - len(missing); job.progress(already, len(demands))
        queue = asyncio.Queue()
        for demand in missing: queue.put_nowait(demand)
        async def worker():
            while not queue.empty():
                await job.checkpoint()
                try: demand = queue.get_nowait()
                except asyncio.QueueEmpty: return
                demand = replace(demand, priority=priority)
                await self.materialize(media_id, demand)
                job.progress(job.completed + 1); queue.task_done()
        tasks = [asyncio.create_task(worker()) for _ in range(min(self._max_downloads, len(missing)))]
        try:
            if tasks: await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks: task.cancel()
            raise
        return presentation, selected

    def _start_download(self, media_id, payload):
        async def runner(job): await self._complete(job, media_id, payload)
        return self.jobs.start("download", runner)

    def _start_batch(self, media_ids, payload, export=False):
        async def runner(job):
            job.progress(0, len(media_ids), "Processando lote")
            for index, media_id in enumerate(media_ids, 1):
                try:
                    if export:
                        await self._export(job, media_id, payload)
                    else:
                        await self._complete(job, media_id, payload)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    safe = re.sub(r"https?://\\S+", "<url>", str(exc))[:500]
                    job.add_failure(media_id, "export" if export else "download", safe)
                job.progress(index, len(media_ids), f"{index}/{len(media_ids)} episódio(s)")
        return self.jobs.start("batch-export" if export else "batch-download", runner)

    async def _write_input(self, media_id, track, rep, target):
        demands = [SegmentDemand(track.id, rep.id, rep.initialization), *(SegmentDemand(track.id, rep.id, segment.identity) for segment in rep.segments)]
        artifacts = [self.locate(media_id, demand) for demand in demands]
        if any(item is None for item in artifacts): raise RuntimeError("faixa ainda possui segmentos ausentes")
        with self.cache.lease(artifacts):
            with target.open("wb") as stream:
                for artifact in artifacts: stream.write(artifact.path.read_bytes())
        return target

    def _sidecar_source(self, media_id, track, fallback: Path) -> tuple[Path, str]:
        prefix = "subtitle:local:"
        if track.id.startswith(prefix):
            attachment_id = track.id[len(prefix):]
            attachment = next((item for item in self.cache.attachments_for(media_id)
                               if item["id"] == attachment_id), None)
            if attachment:
                original = Path(attachment["original_path"])
                if original.is_file():
                    return original, original.suffix.lower()
        return fallback, ".vtt"

    @staticmethod
    def _copy_unique_sidecar(source: Path, destination: Path, language: str, extension: str) -> Path:
        stem = f"{destination.stem}.{_safe_name(language or 'und')}"
        target = destination.with_name(f"{stem}{extension}")
        suffix = 2
        while target.exists():
            target = destination.with_name(f"{stem} ({suffix}){extension}")
            suffix += 1
        temporary = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    async def _export(self, job, media_id, payload):
        presentation, selected = await self._complete(job, media_id, payload, DemandPriority.CANONICAL)
        token = secrets.token_hex(8); inputs = []
        try:
            for index, (track, rep) in enumerate(selected):
                extension = ".vtt" if track.kind == "text" else ".mp4"
                target = self.cache.export_temp / f"{token}-{index}{extension}"
                if track.kind == "text" and rep.initialization.startswith("attachment:"):
                    artifact = self.locate(media_id, SegmentDemand(track.id, rep.id, rep.initialization))
                    shutil.copyfile(artifact.path, target)
                else: await self._write_input(media_id, track, rep, target)
                inputs.append((track, target))
            folder = self.export_path
            for part in await asyncio.to_thread(self.cache.export_hierarchy, media_id): folder /= _safe_name(part)
            folder.mkdir(parents=True, exist_ok=True)
            title = _safe_name(presentation.title); destination = folder / f"{title}.mp4"; suffix = 2
            while destination.exists(): destination = folder / f"{title} ({suffix}).mp4"; suffix += 1
            temporary = self.cache.export_temp / f"{token}.tmp.mp4"
            command = [self.ffmpeg, "-v", "error", "-y"]
            for _, path in inputs: command += ["-i", str(path)]
            for index, (track, _) in enumerate(inputs): command += ["-map", f"{index}:0"]
            command += ["-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text", "-movflags", "+faststart", str(temporary)]
            job.progress(message="Exportando MP4")
            process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            try:
                _, error = await process.communicate()
            except asyncio.CancelledError:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 5)
                except TimeoutError:
                    process.kill()
                    await process.wait()
                raise
            if process.returncode or not temporary.is_file(): raise RuntimeError((error.decode(errors="replace") or "FFmpeg falhou")[-500:])
            os.replace(temporary, destination); digest = await asyncio.to_thread(_digest, destination)
            self.cache.register_export(media_id, presentation.revision_seed, destination, digest)
            for track, path in inputs:
                if track.kind != "text": continue
                sidecar_source, extension = self._sidecar_source(media_id, track, path)
                self._copy_unique_sidecar(sidecar_source, destination, track.language or "und", extension)
            job.progress(job.total, job.total, f"Exportado para {destination.name}")
        finally:
            for _, path in inputs:
                try: path.unlink(missing_ok=True)
                except OSError: pass

    async def _upload_subtitle(self, request):
        media_id = request.query_params.get("media_id", ""); language = request.query_params.get("language", "").strip()
        label = request.query_params.get("label", "").strip() or language
        filename = request.query_params.get("filename", "subtitle.vtt"); extension = Path(filename).suffix.lower()
        if not media_id or not language or extension not in {".ass", ".srt", ".vtt"}: raise HTTPException(422, "Mídia, idioma ou formato inválido")
        raw = await request.body()
        if not raw or len(raw) > 16 * 1024 * 1024: raise HTTPException(422, "Legenda vazia ou grande demais")
        vtt = _subtitle_to_vtt(raw, extension)
        folder = self.cache.attachments / hashlib.sha256(media_id.encode()).hexdigest()[:24]; folder.mkdir(parents=True, exist_ok=True)
        token = secrets.token_hex(8); original = folder / f"{token}{extension}"; derived = folder / f"{token}.vtt"
        original.write_bytes(raw); derived.write_bytes(vtt)
        attachment_id = self.cache.add_attachment(media_id, language, label, original, derived, extension[1:])
        return {"id": attachment_id, "language": language, "label": label}

    async def handle_host_action(self, action, request):
        if action == "cache" and request.method == "GET":
            media = await asyncio.to_thread(self.cache.inventory)
            return {"media": media, "storage": {"cached_bytes": sum(value["cached_bytes"] for value in media),
                                                   "media_count": len(media),
                                                   "export_count": sum(len(value["exports"]) for value in media)},
                    "jobs": self.jobs.list(),
                    "defaults": {"audio_languages": self.options.get("audio_languages", []),
                                 "subtitle_languages": self.options.get("subtitle_languages", []),
                                 "video_quality": self.options.get("video_quality"),
                                 "audio_quality": self.options.get("audio_quality")}}
        if action == "preferences" and request.method == "GET":
            return {"audio_languages": self.options.get("audio_languages", []),
                    "subtitle_languages": self.options.get("subtitle_languages", []),
                    "video_quality": self.options.get("video_quality"),
                    "audio_quality": self.options.get("audio_quality")}
        if action == "preferences" and request.method == "PUT":
            payload = await request.json()
            for key in ("audio_languages", "subtitle_languages"):
                if key in payload and (not isinstance(payload[key], list) or any(not isinstance(value, str) or not value.strip() for value in payload[key])):
                    raise HTTPException(422, f"{key} inválido")
            for key in ("audio_languages", "subtitle_languages", "video_quality", "audio_quality"):
                if key in payload: self.options[key] = payload[key]
            return {key: self.options.get(key) for key in ("audio_languages", "subtitle_languages", "video_quality", "audio_quality")}
        if action == "catalog/refresh" and request.method == "POST":
            for path in self._metadata.glob("*.json"):
                try: path.unlink()
                except OSError: pass
            return {"refreshed": True}
        if action == "presentation" and request.method == "GET":
            media_id = request.query_params.get("media_id", "")
            return self._presentation_data(await self.inspect(media_id))
        if action == "collection-summary" and request.method == "GET":
            parent_id = request.query_params.get("parent_id", "")
            if not parent_id:
                raise HTTPException(422, "parent_id é obrigatório")
            descendants = set(await asyncio.to_thread(self.cache.descendants, parent_id))
            media = await asyncio.to_thread(self.cache.inventory)
            return {"media": [item for item in media if item["media_id"] in descendants]}
        if action == "download" and request.method == "POST":
            payload = await request.json(); media_id = str(payload.get("media_id", ""))
            if not media_id: raise HTTPException(422, "media_id é obrigatório")
            return {"job": self._start_download(media_id, payload).view()}
        if action == "export-mp4" and request.method == "POST":
            payload = await request.json(); media_id = str(payload.get("media_id", ""))
            if not media_id: raise HTTPException(422, "media_id é obrigatório")
            job = self.jobs.start("export-mp4", lambda value: self._export(value, media_id, payload))
            return {"job": job.view()}
        if action == "download-export" and request.method == "POST":
            payload = await request.json(); media_id = str(payload.get("media_id", ""))
            if not media_id: raise HTTPException(422, "media_id é obrigatório")
            job = self.jobs.start("download-export", lambda value: self._export(value, media_id, payload))
            return {"job": job.view()}
        if action in {"batch-download", "batch-download-export"} and request.method == "POST":
            payload = await request.json(); raw_ids = payload.get("media_ids")
            if not isinstance(raw_ids, list) or not raw_ids or any(not isinstance(value, str) or not value for value in raw_ids):
                raise HTTPException(422, "media_ids deve ser uma lista não vazia")
            unique_ids = list(dict.fromkeys(raw_ids))
            return {"job": self._start_batch(unique_ids, payload, action.endswith("export")).view()}
        if action == "subtitles/upload" and request.method == "POST": return await self._upload_subtitle(request)
        if action == "jobs" and request.method == "GET": return {"jobs": self.jobs.list()}
        if action == "jobs/report" and request.method == "GET":
            return {"jobs": [{"id": job["id"], "kind": job["kind"], "state": job["state"], "failures": job["failures"]}
                            for job in self.jobs.list() if job["failures"]]}
        if action.startswith("jobs/"):
            parts = action.split("/")
            if len(parts) == 2 and request.method == "GET": return {"job": self.jobs.get(parts[1]).view()}
            if len(parts) == 3 and request.method == "POST":
                operation = {"pause": self.jobs.pause, "resume": self.jobs.resume, "cancel": self.jobs.cancel}.get(parts[2])
                if operation: return {"job": operation(parts[1]).view()}
        if action == "cache/cleanup-preview" and request.method == "POST":
            payload = await request.json()
            if payload.get("mode") == "orphans": return await asyncio.to_thread(self.cache.orphan_preview)
            result = await asyncio.to_thread(self.cache.cleanup_preview, payload); result.pop("paths", None); return result
        if action == "cache/cleanup" and request.method == "POST":
            payload = await request.json()
            if payload.get("mode") == "orphans": return await asyncio.to_thread(self.cache.remove_orphans)
            return await asyncio.to_thread(self.cache.cleanup, payload)
        return None
