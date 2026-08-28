import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path: sys.path.insert(0, SRC_DIR)

from media_sources.plugin_runtime import discover_plugins


class PluginRuntimeTests(unittest.TestCase):
    def test_builtins_are_discovered_with_host_modules(self):
        catalog = discover_plugins()
        self.assertEqual(set(catalog.plugins), {"directory", "crunchyroll"})
        self.assertTrue(all(plugin.host_module.is_file() for plugin in catalog.plugins.values()))

    def test_bad_plugin_is_diagnostic_not_process_failure(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / "broken"; folder.mkdir()
            (folder / "manifest.json").write_text(json.dumps({"type":"broken", "interface_version":999}), encoding="utf-8")
            catalog = discover_plugins(root)
            self.assertEqual(catalog.plugins, {}); self.assertEqual(catalog.diagnostics[0].plugin, "broken")
