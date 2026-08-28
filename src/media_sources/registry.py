from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .errors import InvalidSourceConfiguration, SourceNotFound
from .models import MediaSource, SourceSummary
from .plugin_runtime import LoadedPlugin, PluginCatalog, PluginDiagnostic, discover_plugins


SOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _safe_plugin_error(exc: Exception, options: dict) -> str:
    message = str(exc) or type(exc).__name__
    for key, value in options.items():
        if isinstance(value, str) and value and (key.endswith("path") or key in {"etp_rt", "token", "cookie", "secret"}):
            message = message.replace(value, "<redacted>")
    message = re.sub(r"https?://\S+", "<url>", message)
    return f"{type(exc).__name__}: {message[:400]}"


@dataclass(frozen=True)
class RegisteredSource:
    summary: SourceSummary
    source: MediaSource
    plugin: LoadedPlugin


class MediaSourceRegistry:
    def __init__(self, entries: list[RegisteredSource], diagnostics: tuple[PluginDiagnostic, ...] = ()):
        self._entries = tuple(entries)
        self._by_id = {entry.summary.id: entry for entry in entries}
        self.diagnostics = diagnostics

    @property
    def summaries(self) -> tuple[SourceSummary, ...]:
        return tuple(entry.summary for entry in self._entries)

    def playback_origins(self) -> dict[str, object]:
        return {entry.summary.id: entry.source for entry in self._entries
                if "playback" in entry.summary.capabilities and hasattr(entry.source, "inspect")}

    def registered(self, source_id: str) -> RegisteredSource:
        try:
            return self._by_id[source_id]
        except KeyError as exc:
            raise SourceNotFound("origem não encontrada") from exc

    def get(self, source_id: str) -> MediaSource:
        return self.registered(source_id).source

    def host_module(self, source_id: str) -> Path:
        entry = self.registered(source_id)
        if entry.plugin.host_module is None:
            raise SourceNotFound("extensão de host não encontrada")
        return entry.plugin.host_module


def build_source_registry(configured_sources: object, plugin_catalog: PluginCatalog | None = None) -> MediaSourceRegistry:
    if not isinstance(configured_sources, list):
        raise InvalidSourceConfiguration("sources deve ser uma lista")
    catalog = plugin_catalog or discover_plugins()
    entries: list[RegisteredSource] = []
    diagnostics = list(catalog.diagnostics)
    seen: set[str] = set()
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
        if not isinstance(source_type, str) or not isinstance(label, str) or not label.strip() or not isinstance(options, dict):
            raise InvalidSourceConfiguration(f"configuração inválida na origem {source_id}")
        plugin = catalog.plugins.get(source_type)
        if plugin is None:
            diagnostics.append(PluginDiagnostic(source_id, f"plugin ausente para o tipo {source_type}"))
            continue
        try:
            source = plugin.factory(source_id, options)
        except Exception as exc:
            diagnostics.append(PluginDiagnostic(source_id, _safe_plugin_error(exc, options)))
            continue
        capabilities = ["browse", "search"]
        if getattr(source, "playback_available", source_type == "crunchyroll"):
            capabilities.append("playback")
        if plugin.host_module is not None:
            capabilities.append("host-extension")
        summary = SourceSummary(source_id, label.strip(), tuple(capabilities), source_type,
                                f"/host/{source_id}/module.js" if plugin.host_module else None)
        entries.append(RegisteredSource(summary, source, plugin))
    return MediaSourceRegistry(entries, tuple(diagnostics))
