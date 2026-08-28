from __future__ import annotations

import importlib
import importlib.util
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


PLUGIN_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
INTERFACE_VERSION = 1


@dataclass(frozen=True)
class PluginDiagnostic:
    plugin: str
    message: str


@dataclass(frozen=True)
class LoadedPlugin:
    type_name: str
    version: str
    folder: Path
    factory: Callable[[str, dict[str, Any]], object]
    host_module: Path | None = None
    python_dependencies: tuple[str, ...] = ()


@dataclass(frozen=True)
class PluginCatalog:
    plugins: dict[str, LoadedPlugin]
    diagnostics: tuple[PluginDiagnostic, ...]


def discover_plugins(root: str | Path | None = None) -> PluginCatalog:
    plugin_root = Path(root) if root is not None else Path(__file__).with_name("plugins")
    loaded: dict[str, LoadedPlugin] = {}
    diagnostics: list[PluginDiagnostic] = []
    if not plugin_root.is_dir():
        return PluginCatalog({}, (PluginDiagnostic(str(plugin_root), "pasta de plugins ausente"),))

    for folder in sorted(plugin_root.iterdir(), key=lambda value: value.name.casefold()):
        if not folder.is_dir() or folder.name.startswith("_"):
            continue
        manifest_path = folder / "manifest.json"
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("manifesto deve conter um objeto")
            type_name = raw.get("type")
            if not isinstance(type_name, str) or not PLUGIN_NAME.fullmatch(type_name):
                raise ValueError("type inválido")
            if folder.name != type_name:
                raise ValueError("a pasta do plugin deve ter o mesmo nome de type")
            if raw.get("interface_version") != INTERFACE_VERSION:
                raise ValueError(f"interface_version incompatível; esperado {INTERFACE_VERSION}")
            if type_name in loaded:
                raise ValueError(f"type duplicado: {type_name}")
            raw_dependencies = raw.get("python_dependencies", [])
            if not isinstance(raw_dependencies, list) or any(not isinstance(value, str) or not value for value in raw_dependencies):
                raise ValueError("python_dependencies deve ser uma lista de módulos")
            dependencies = tuple(raw_dependencies)
            missing = [value for value in dependencies if importlib.util.find_spec(value) is None]
            if missing:
                raise ValueError("dependências Python ausentes: " + ", ".join(missing))
            backend = raw.get("backend")
            if not isinstance(backend, str) or ":" not in backend:
                raise ValueError("backend deve usar modulo:callable")
            module_name, callable_name = backend.split(":", 1)
            if not module_name or not callable_name or "." in module_name:
                raise ValueError("backend deve apontar para um módulo dentro do plugin")
            package = f"media_sources.plugins.{folder.name}.{module_name}"
            factory = getattr(importlib.import_module(package), callable_name)
            if not callable(factory):
                raise ValueError("factory do backend não é chamável")
            host_name = raw.get("host_module")
            host_module = None
            if host_name is not None:
                if not isinstance(host_name, str) or Path(host_name).name != host_name:
                    raise ValueError("host_module deve ser um arquivo local ao plugin")
                host_module = (folder / host_name).resolve(strict=True)
                host_module.relative_to(folder.resolve())
            version = raw.get("version", "0")
            if not isinstance(version, str) or not version.strip():
                raise ValueError("version inválida")
            loaded[type_name] = LoadedPlugin(type_name, version, folder.resolve(), factory, host_module, dependencies)
        except Exception as exc:
            diagnostics.append(PluginDiagnostic(folder.name, f"{type(exc).__name__}: {exc}"))
    return PluginCatalog(loaded, tuple(diagnostics))
