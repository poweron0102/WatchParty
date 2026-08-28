import json
import os
import sys
import unittest

import httpx

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path: sys.path.insert(0, SRC_DIR)

from media_sources.crunchyroll_api import CrunchyrollApi


class CrunchyrollApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_cookie_auth_uses_current_web_contract(self):
        captured = {}

        async def handler(request):
            captured["url"] = str(request.url)
            captured["authorization"] = request.headers.get("authorization")
            captured["cookie"] = request.headers.get("cookie")
            captured["form"] = dict(item.split("=", 1) for item in request.content.decode().split("&"))
            return httpx.Response(200, json={"access_token": "token", "expires_in": 300})

        api = CrunchyrollApi("etp_rt=secret-value; path=/", "pt-BR", httpx.MockTransport(handler))
        try: await api._authenticate()
        finally: await api.close()

        self.assertEqual(captured["url"], "https://www.crunchyroll.com/auth/v1/token")
        self.assertEqual(captured["authorization"], "Basic bm9haWhkZXZtXzZpeWcwYThsMHE6")
        self.assertIn("etp_rt=secret-value", captured["cookie"])
        self.assertIn("device_id=", captured["cookie"])
        self.assertEqual(captured["form"]["grant_type"], "etp_rt_cookie")
        self.assertIn("device_id", captured["form"])
        self.assertIn("device_type", captured["form"])


if __name__ == "__main__": unittest.main()
