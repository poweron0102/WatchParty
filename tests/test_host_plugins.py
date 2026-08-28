import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT, "src")
if SRC_DIR not in sys.path: sys.path.insert(0, SRC_DIR)
os.chdir(ROOT)

from fastapi.testclient import TestClient  # noqa: E402
from server_setup import app  # noqa: E402
import http_routes  # noqa: F401,E402
from state import server_state  # noqa: E402


class HostPluginApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.client = TestClient(app)
    @classmethod
    def tearDownClass(cls): cls.client.close()

    def setUp(self):
        self.previous = server_state["allow_remote_host_admin"]

    def tearDown(self):
        server_state["allow_remote_host_admin"] = self.previous

    def test_host_and_plugin_modules_follow_remote_toggle(self):
        server_state["allow_remote_host_admin"] = False
        self.assertEqual(self.client.get("/host").status_code, 403)
        server_state["allow_remote_host_admin"] = True
        self.assertEqual(self.client.get("/host").status_code, 200)
        sources = self.client.get("/api/sources").json()["sources"]
        local = next(source for source in sources if source["id"] == "local")
        self.assertEqual(local["host_module"], "/host/local/module.js")
        module = self.client.get(local["host_module"])
        self.assertEqual(module.status_code, 200); self.assertIn("export async function mount", module.text)

    def test_plugin_action_stays_in_source_namespace(self):
        server_state["allow_remote_host_admin"] = True
        response = self.client.get("/host/local/previews/status")
        self.assertEqual(response.status_code, 200); self.assertIn("writable", response.json())
        self.assertEqual(self.client.get("/host/local/unknown").status_code, 404)

    def test_remote_toggle_requires_loopback_peer_and_loopback_browser_origin(self):
        local = TestClient(app, base_url="http://localhost", client=("127.0.0.1", 51000))
        rebound = TestClient(app, base_url="http://attacker.example", client=("127.0.0.1", 51001))
        try:
            server_state["allow_remote_host_admin"] = False
            self.assertEqual(local.get("/host").status_code, 200)
            self.assertEqual(rebound.get("/host").status_code, 403)
            with patch("http_routes.persist_remote_host_admin"):
                denied = local.put("/api/host/remote-access", headers={"Origin":"https://attacker.example"},
                                   json={"enabled":True})
                self.assertEqual(denied.status_code, 403)
                allowed = local.put("/api/host/remote-access", headers={"Origin":"http://localhost:8000"},
                                    json={"enabled":True})
                self.assertEqual(allowed.status_code, 200)
        finally:
            local.close()
            rebound.close()


if __name__ == "__main__": unittest.main()
