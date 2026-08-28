from __future__ import annotations

from pathlib import Path
from typing import Any

from media_sources.errors import InvalidSourceConfiguration

from .source import ManagedCrunchyrollSource


def _languages(value, name, require_explicit=False):
    if not isinstance(value, list) or not value or any(not isinstance(v, str) or not v.strip() for v in value):
        raise InvalidSourceConfiguration(f"{name} deve ser uma lista não vazia")
    if len(value) != len(set(value)) or ("*" in value and value[-1] != "*"):
        raise InvalidSourceConfiguration(f"{name} contém duplicatas ou wildcard inválido")
    if require_explicit and value[0] == "*":
        raise InvalidSourceConfiguration("audio_languages exige um idioma explícito")


def create_source(source_id: str, options: dict[str, Any]):
    allowed = {"cache_path", "export_path", "etp_rt", "locale", "audio_languages", "subtitle_languages",
               "video_quality", "audio_quality", "metadata_ttl_hours", "worker_idle_seconds",
               "max_segment_downloads", "max_playback_sessions", "worker_path", "ffmpeg_path",
               "widevine_device_path", "client_id_path", "private_key_path"}
    required = allowed - {"export_path", "widevine_device_path", "client_id_path", "private_key_path"}
    if set(options) - allowed or not required.issubset(options):
        raise InvalidSourceConfiguration("opções ausentes ou desconhecidas para crunchyroll")
    for field in ("cache_path", "etp_rt", "locale", "video_quality", "audio_quality", "worker_path", "ffmpeg_path"):
        if not isinstance(options.get(field), str) or not options[field].strip():
            raise InvalidSourceConfiguration(f"{field} é obrigatório")
    raw_device, raw_client, raw_key = (options.get("widevine_device_path"), options.get("client_id_path"),
                                       options.get("private_key_path"))
    has_wvd = isinstance(raw_device, str) and bool(raw_device.strip())
    has_raw_device = all(isinstance(value, str) and bool(value.strip()) for value in (raw_client, raw_key))
    has_partial_raw = any(value is not None for value in (raw_client, raw_key)) and not has_raw_device
    if has_partial_raw or has_wvd == has_raw_device:
        raise InvalidSourceConfiguration("configure widevine_device_path ou o par client_id_path/private_key_path")
    _languages(options["audio_languages"], "audio_languages", True)
    _languages(options["subtitle_languages"], "subtitle_languages")
    for field in ("metadata_ttl_hours", "worker_idle_seconds"):
        if isinstance(options.get(field), bool) or not isinstance(options.get(field), (int, float)) or options[field] <= 0:
            raise InvalidSourceConfiguration(f"{field} deve ser positivo")
    for field in ("max_segment_downloads", "max_playback_sessions"):
        if isinstance(options.get(field), bool) or not isinstance(options.get(field), int) or options[field] <= 0:
            raise InvalidSourceConfiguration(f"{field} deve ser um inteiro positivo")
    path = Path(options["cache_path"]); path = path if path.is_absolute() else Path.cwd() / path
    try: path.mkdir(parents=True, exist_ok=True)
    except OSError as exc: raise InvalidSourceConfiguration("cache_path não é gravável") from exc
    worker = Path(options["worker_path"]); worker = worker if worker.is_absolute() else Path.cwd() / worker
    public_options = {key: value for key, value in options.items() if key != "etp_rt"}
    return ManagedCrunchyrollSource(source_id, path, options["etp_rt"], options["locale"], int(options["metadata_ttl_hours"]),
                                   worker_path=worker, worker_options=public_options)
