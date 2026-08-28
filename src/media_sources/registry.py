from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .directory import DirectorySource
from .crunchyroll import CrunchyrollSource
from .errors import InvalidSourceConfiguration, SourceNotFound
from .models import MediaSource, SourceSummary

SOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class RegisteredSource:
    summary: SourceSummary
    source: MediaSource


class MediaSourceRegistry:
    def __init__(self, entries: list[RegisteredSource]):
        self._entries = tuple(entries)
        self._by_id = {entry.summary.id: entry for entry in entries}

    @property
    def summaries(self) -> tuple[SourceSummary, ...]:
        return tuple(entry.summary for entry in self._entries)

    def playback_origins(self) -> dict[str, object]:
        return {entry.summary.id: entry.source for entry in self._entries
                if "playback" in entry.summary.capabilities and hasattr(entry.source, "inspect")}

    def get(self, source_id: str) -> MediaSource:
        try:
            return self._by_id[source_id].source
        except KeyError as exc:
            raise SourceNotFound("origem não encontrada") from exc


def _directory_factory(options: dict[str, Any]) -> MediaSource:
    allowed = {"path", "ffmpeg_path", "transcode_profile", "hardware_acceleration"}
    if set(options) - allowed or not isinstance(options.get("path"), str) or not options["path"].strip():
        raise InvalidSourceConfiguration("opções inválidas para a origem directory")
    acceleration = options.get("hardware_acceleration", "auto")
    if acceleration not in ("auto", "software"):
        raise InvalidSourceConfiguration("hardware_acceleration inválido")
    return DirectorySource(options["path"], options.get("ffmpeg_path", "ffmpeg.exe"),
                           options.get("transcode_profile", "chrome-h264-aac"), acceleration)


def _languages(value, name, require_explicit=False):
    if not isinstance(value, list) or not value or any(not isinstance(v, str) or not v.strip() for v in value):
        raise InvalidSourceConfiguration(f"{name} deve ser uma lista não vazia")
    if len(value) != len(set(value)) or ("*" in value and value[-1] != "*"):
        raise InvalidSourceConfiguration(f"{name} contém duplicatas ou wildcard inválido")
    if require_explicit and value[0] == "*":
        raise InvalidSourceConfiguration("audio_languages exige um idioma explícito")


def _crunchyroll_factory(options: dict[str, Any]) -> MediaSource:
    allowed = {"cache_path", "etp_rt", "locale", "audio_languages", "subtitle_languages", "video_quality",
               "audio_quality", "metadata_ttl_hours", "finalization_idle_minutes", "worker_idle_seconds",
               "max_segment_downloads", "max_playback_sessions", "worker_path", "ffmpeg_path", "widevine_device_path",
               "client_id_path", "private_key_path"}
    required = allowed - {"widevine_device_path", "client_id_path", "private_key_path"}
    if set(options) - allowed or not required.issubset(options):
        raise InvalidSourceConfiguration("opções ausentes ou desconhecidas para crunchyroll")
    for field in ("cache_path", "etp_rt", "locale", "video_quality", "audio_quality", "worker_path", "ffmpeg_path"):
        if not isinstance(options.get(field), str) or not options[field].strip():
            raise InvalidSourceConfiguration(f"{field} é obrigatório")
    raw_device = options.get("widevine_device_path")
    raw_client = options.get("client_id_path")
    raw_key = options.get("private_key_path")
    has_wvd = isinstance(raw_device, str) and bool(raw_device.strip())
    has_raw_device = all(isinstance(value, str) and bool(value.strip()) for value in (raw_client, raw_key))
    has_partial_raw = any(value is not None for value in (raw_client, raw_key)) and not has_raw_device
    if has_partial_raw or has_wvd == has_raw_device:
        raise InvalidSourceConfiguration("configure widevine_device_path ou o par client_id_path/private_key_path")
    _languages(options["audio_languages"], "audio_languages", True)
    _languages(options["subtitle_languages"], "subtitle_languages")
    for field in ("metadata_ttl_hours", "finalization_idle_minutes", "worker_idle_seconds", "max_segment_downloads", "max_playback_sessions"):
        if isinstance(options.get(field), bool) or not isinstance(options.get(field), (int, float)) or options[field] <= 0:
            raise InvalidSourceConfiguration(f"{field} deve ser positivo")
    path = Path(options["cache_path"]); path = path if path.is_absolute() else Path.cwd() / path
    try: path.mkdir(parents=True, exist_ok=True)
    except OSError as exc: raise InvalidSourceConfiguration("cache_path não é gravável") from exc
    worker = Path(options["worker_path"]); worker = worker if worker.is_absolute() else Path.cwd() / worker
    public_options = {key: value for key, value in options.items() if key != "etp_rt"}
    return CrunchyrollSource(path, options["etp_rt"], options["locale"], int(options["metadata_ttl_hours"]),
                            worker_path=worker, worker_options=public_options)


FACTORIES: dict[str, Callable[[dict[str, Any]], MediaSource]] = {"directory": _directory_factory, "crunchyroll": _crunchyroll_factory}


def build_source_registry(configured_sources: object) -> MediaSourceRegistry:
    if not isinstance(configured_sources, list):
        raise InvalidSourceConfiguration("sources deve ser uma lista")
    entries, seen = [], set()
    for index, raw in enumerate(configured_sources):
        if not isinstance(raw, dict):
            raise InvalidSourceConfiguration(f"sources[{index}] deve ser um objeto")
        enabled = raw.get("enabled", True)
        if not isinstance(enabled, bool):
            raise InvalidSourceConfiguration(f"sources[{index}].enabled deve ser booleano")
        required = ("id", "type", "label", "options")
        if any(key not in raw for key in required):
            raise InvalidSourceConfiguration(f"sources[{index}] não contém todos os campos obrigatórios")
        source_id = raw["id"]
        if not isinstance(source_id, str) or not SOURCE_ID.fullmatch(source_id):
            raise InvalidSourceConfiguration(f"sources[{index}].id é inválido")
        if source_id in seen:
            raise InvalidSourceConfiguration(f"id de origem duplicado: {source_id}")
        seen.add(source_id)
        if not enabled:
            continue
        source_type, label, options = raw["type"], raw["label"], raw["options"]
        if source_type not in FACTORIES:
            raise InvalidSourceConfiguration(f"tipo desconhecido na origem {source_id}")
        if not isinstance(label, str) or not label.strip() or not isinstance(options, dict):
            raise InvalidSourceConfiguration(f"configuração inválida na origem {source_id}")
        try:
            source = FACTORIES[source_type](options)
        except InvalidSourceConfiguration as exc:
            raise InvalidSourceConfiguration(f"origem {source_id}: {exc}") from exc
        capabilities = ["browse", "search"]
        if getattr(source, "playback_available", source_type == "crunchyroll"):
            capabilities.append("playback")
        entries.append(RegisteredSource(SourceSummary(source_id, label.strip(), tuple(capabilities)), source))
    if not entries:
        raise InvalidSourceConfiguration("ao menos uma origem deve estar habilitada")
    return MediaSourceRegistry(entries)
