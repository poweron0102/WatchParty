from __future__ import annotations

import asyncio
import os
import secrets
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from fastapi import HTTPException

from media_sources.errors import InvalidSourceConfiguration

from .source_core import DirectorySource, VIDEO_EXTENSIONS


class DirectoryPluginSource(DirectorySource):
    owns_cache = True

    def __init__(self, *args, **kwargs):
        kwargs.pop("source_id")
        super().__init__(*args, **kwargs)
        self._preview_jobs: dict[str, dict] = {}

    def _preview_target(self, media_id: str, entry_type: str, variant: str) -> tuple[Path, Path]:
        if variant not in {"poster", "thumbnail"} or entry_type not in {"collection", "playable"}:
            raise HTTPException(422, "variant ou entry_type inválido")
        try:
            item = self._resolve(media_id)
        except Exception as exc:
            raise HTTPException(404, "Item não encontrado") from exc
        if entry_type == "collection":
            if not item.is_dir(): raise HTTPException(422, "O item não é uma coleção")
            target = item / ".previews" / f"{variant}.png"
        else:
            if not item.is_file() or item.suffix.lower() not in VIDEO_EXTENSIONS:
                raise HTTPException(422, "O item não é um vídeo")
            target = item.parent / ".previews" / f"{item.stem}_{variant}.png"
        try:
            target = target.resolve(strict=False); target.relative_to(self._root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(422, "Destino de preview escapa da origem") from exc
        return item, target

    @staticmethod
    def _decode_image(raw: bytes, variant: str) -> bytes:
        if not raw or len(raw) > 64 * 1024 * 1024:
            raise HTTPException(422, "Imagem vazia ou grande demais")
        image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise HTTPException(422, "Arquivo não é uma imagem reconhecida")
        width, height = ((600, 900) if variant == "poster" else (1280, 720))
        source_ratio, target_ratio = image.shape[1] / image.shape[0], width / height
        if source_ratio > target_ratio:
            crop = int(image.shape[0] * target_ratio); left = (image.shape[1] - crop) // 2
            image = image[:, left:left + crop]
        else:
            crop = int(image.shape[1] / target_ratio); top = (image.shape[0] - crop) // 2
            image = image[top:top + crop, :]
        image = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".png", image)
        if not ok: raise HTTPException(500, "Não foi possível codificar a imagem")
        return encoded.tobytes()

    @staticmethod
    def _publish(target: Path, raw: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")
        try:
            temporary.write_bytes(raw); os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    async def _generate_one(self, video: Path, target: Path, overwrite: bool) -> str:
        if target.exists() and not overwrite: return "skipped"
        def generate():
            capture = cv2.VideoCapture(str(video))
            try:
                if not capture.isOpened(): raise RuntimeError("não foi possível abrir o vídeo")
                frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)); capture.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(frames * .3)))
                ok, frame = capture.read()
                if not ok: raise RuntimeError("não foi possível extrair um frame")
                ok, encoded = cv2.imencode(".png", frame)
                if not ok: raise RuntimeError("não foi possível codificar o frame")
                self._publish(target, self._decode_image(encoded.tobytes(), "thumbnail"))
            finally: capture.release()
        await asyncio.to_thread(generate)
        return "created"

    async def _bulk_generate(self, job_id: str, parent_id: str, overwrite: bool):
        job = self._preview_jobs[job_id]
        try:
            parent = self._resolve(parent_id or None)
            videos = [path for path in parent.rglob("*") if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
                      and not any(part.startswith(".") for part in path.relative_to(self._root).parts)]
            job.update(total=len(videos), state="running")
            for video in videos:
                try:
                    _, target = self._preview_target(self._id(video), "playable", "thumbnail")
                    outcome = await self._generate_one(video, target, overwrite)
                    job[outcome] = job.get(outcome, 0) + 1
                except Exception as exc:
                    job["failed"] = job.get("failed", 0) + 1; job["last_error"] = str(exc)[:200]
                job["completed"] += 1
            job["state"] = "completed"
        except Exception as exc:
            job.update(state="failed", error=str(exc)[:240])

    async def handle_host_action(self, action, request):
        if action == "previews/status" and request.method == "GET":
            return {"writable": os.access(self._root, os.W_OK), "jobs": list(self._preview_jobs.values())}
        if action == "previews/upload" and request.method == "POST":
            media_id = request.query_params.get("media_id", "")
            variant = request.query_params.get("variant", "thumbnail")
            entry_type = request.query_params.get("entry_type", "playable")
            _, target = self._preview_target(media_id, entry_type, variant)
            raw = await request.body(); encoded = await asyncio.to_thread(self._decode_image, raw, variant)
            await asyncio.to_thread(self._publish, target, encoded)
            return {"updated": True, "resource_id": self._id(target)}
        if action == "previews/generate" and request.method == "POST":
            payload = await request.json(); media_id = str(payload.get("media_id", ""))
            video, target = self._preview_target(media_id, "playable", "thumbnail")
            outcome = await self._generate_one(video, target, bool(payload.get("overwrite")))
            return {"outcome": outcome, "resource_id": self._id(target)}
        if action == "previews/generate-bulk" and request.method == "POST":
            payload = await request.json(); job_id = secrets.token_urlsafe(12)
            job = {"id": job_id, "state": "queued", "completed": 0, "total": 0, "created": 0, "skipped": 0, "failed": 0}
            self._preview_jobs[job_id] = job
            asyncio.create_task(self._bulk_generate(job_id, str(payload.get("parent_id", "")), bool(payload.get("overwrite"))))
            return {"job": job}
        return None


def create_source(_source_id: str, options: dict[str, Any]):
    allowed = {"path", "ffmpeg_path", "transcode_profile", "hardware_acceleration", "memory_cache_bytes"}
    if set(options) - allowed or not isinstance(options.get("path"), str) or not options["path"].strip():
        raise InvalidSourceConfiguration("opções inválidas para a origem directory")
    acceleration = options.get("hardware_acceleration", "auto")
    if acceleration not in ("auto", "software"):
        raise InvalidSourceConfiguration("hardware_acceleration inválido")
    memory = options.get('memory_cache_bytes', 256 * 1024 * 1024)
    if isinstance(memory, bool) or not isinstance(memory, int) or memory < 0:
        raise InvalidSourceConfiguration('memory_cache_bytes deve ser um inteiro não negativo')
    return DirectoryPluginSource(options["path"], options.get("ffmpeg_path", "ffmpeg.exe"),
                                 options.get("transcode_profile", "chrome-h264-aac"), acceleration, memory,
                                 source_id=_source_id)
