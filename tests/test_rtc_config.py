import base64
import hashlib
import hmac
import os
import sys
import unittest


SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from rtc_config import (  # noqa: E402
    DEFAULT_ICE_SERVERS,
    build_rtc_config,
    generate_turn_credentials,
    managed_turn_server,
    normalize_ice_servers,
    split_ice_servers,
)


class RtcConfigTests(unittest.TestCase):
    def test_normalize_ice_servers_accepts_strings_and_objects(self):
        servers = normalize_ice_servers([
            "stun:stun.example.com:3478",
            {"urls": "turn:turn.example.com:3478", "username": "user", "credential": "pass"},
            None,
            {"missing": "urls"},
        ])

        self.assertEqual(len(servers), 2)
        self.assertEqual(servers[0], {"urls": "stun:stun.example.com:3478"})
        self.assertEqual(servers[1]["username"], "user")

    def test_normalize_ice_servers_uses_default_for_invalid_input(self):
        self.assertEqual(normalize_ice_servers("invalid"), DEFAULT_ICE_SERVERS)
        self.assertEqual(normalize_ice_servers([]), DEFAULT_ICE_SERVERS)

    def test_split_ice_servers_separates_mixed_url_lists(self):
        stun, turn = split_ice_servers([{
            "urls": ["stun:stun.example.com", "turn:turn.example.com"],
            "username": "user",
            "credential": "pass",
        }])

        self.assertEqual(stun, [{"urls": ["stun:stun.example.com"]}])
        self.assertEqual(turn, [{
            "urls": ["turn:turn.example.com"],
            "username": "user",
            "credential": "pass",
        }])

    def test_generate_turn_credentials_matches_known_hmac(self):
        credentials = generate_turn_credentials(
            "test-secret", "alice", 3600, now=1_700_000_000
        )

        self.assertEqual(credentials["username"], "1700003600:alice")
        self.assertEqual(credentials["credential"], "Ng7w0UfmbgfuFIyleDy63RrsEh8=")

        expected = base64.b64encode(hmac.new(
            b"test-secret",
            credentials["username"].encode(),
            hashlib.sha1,
        ).digest()).decode()
        self.assertEqual(credentials["credential"], expected)

    def test_modes_select_expected_servers_and_policy(self):
        base = [
            {"urls": "stun:stun.example.com"},
            {"urls": "turn:legacy.example.com", "username": "u", "credential": "p"},
        ]
        managed = managed_turn_server(
            "2001:db8::1", 3478, "secret", "client", 86400, now=100
        )

        off = build_rtc_config(base, "off", managed)
        automatic = build_rtc_config(base, "auto", managed)
        relay = build_rtc_config(base, "relay", managed)

        self.assertEqual(off["iceServers"], [{"urls": "stun:stun.example.com"}])
        self.assertEqual(off["iceTransportPolicy"], "all")
        self.assertEqual(len(automatic["iceServers"]), 3)
        self.assertEqual(relay["iceTransportPolicy"], "relay")
        self.assertEqual(len(relay["iceServers"]), 2)
        self.assertIn("turn:[2001:db8::1]:3478?transport=udp", managed["urls"])


if __name__ == "__main__":
    unittest.main()
