import os
import sys
import unittest
from unittest.mock import patch


PROJECT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(PROJECT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
os.chdir(PROJECT_DIR)

from fastapi.testclient import TestClient  # noqa: E402
import http_routes  # noqa: E402,F401
from server_setup import app  # noqa: E402
from state import create_server_state, server_state  # noqa: E402


class RtcApiTests(unittest.TestCase):
    def setUp(self):
        server_state.clear()
        server_state.update(create_server_state())
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_default_mode_is_auto_and_survives_page_reload(self):
        with patch.object(http_routes, "TURN_CONFIGURED", True):
            first = self.client.get("/api/rtc_mode")
            second = self.client.get("/api/rtc_mode")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), {"mode": "auto", "turnConfigured": True})
        self.assertEqual(second.json()["mode"], "auto")
        self.assertEqual(create_server_state()["rtc_mode"], "auto")

    def test_mode_changes_are_kept_in_server_memory(self):
        with patch.object(http_routes, "TURN_CONFIGURED", True):
            response = self.client.put("/api/rtc_mode", json={"mode": "relay"})
            current = self.client.get("/api/rtc_mode")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(current.json()["mode"], "relay")

    def test_invalid_mode_is_rejected(self):
        response = self.client.put("/api/rtc_mode", json={"mode": "invalid"})
        self.assertEqual(response.status_code, 422)

    def test_turn_modes_are_rejected_when_turn_is_missing(self):
        server_state["rtc_mode"] = "off"
        with patch.object(http_routes, "TURN_CONFIGURED", False):
            automatic = self.client.put("/api/rtc_mode", json={"mode": "auto"})
            relay = self.client.put("/api/rtc_mode", json={"mode": "relay"})

        self.assertEqual(automatic.status_code, 409)
        self.assertEqual(relay.status_code, 409)
        self.assertEqual(server_state["rtc_mode"], "off")

    def test_rtc_config_contains_temporary_turn_credentials(self):
        server_state["rtc_mode"] = "relay"
        with (
            patch.object(http_routes, "TURN_HOST", "turn.example.com"),
            patch.object(http_routes, "TURN_SECRET", "test-secret"),
            patch.object(http_routes, "TURN_PORT", 3478),
            patch.object(http_routes, "TURN_CREDENTIAL_TTL", 86400),
        ):
            response = self.client.get("/api/rtc_config")

        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["mode"], "relay")
        self.assertEqual(data["iceTransportPolicy"], "relay")
        self.assertEqual(len(data["iceServers"]), 1)
        self.assertIn("username", data["iceServers"][0])
        self.assertIn("credential", data["iceServers"][0])


if __name__ == "__main__":
    unittest.main()
