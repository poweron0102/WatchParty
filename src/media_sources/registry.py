from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .directory import DirectorySource
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

    def get(self, source_id: str) -> MediaSource:
        try:
            return self._by_id[source_id].source
        except KeyError as exc:
            raise SourceNotFound("origem não encontrada") from exc


def _directory_factory(options: dict[str, Any]) -> MediaSource:
    if set(options) != {"path"} or not isinstance(options.get("path"), str) or not options["path"].strip():
        raise InvalidSourceConfiguration("a origem directory exige somente options.path")
    return DirectorySource(options["path"])


FACTORIES: dict[str, Callable[[dict[str, Any]], MediaSource]] = {"directory": _directory_factory}


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
        entries.append(RegisteredSource(SourceSummary(source_id, label.strip()), source))
    if not entries:
        raise InvalidSourceConfiguration("ao menos uma origem deve estar habilitada")
    return MediaSourceRegistry(entries)
