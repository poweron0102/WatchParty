import os
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path: sys.path.insert(0, SRC_DIR)

from media_sources.plugins.directory.backend import DirectoryPluginSource


class FakeRequest:
    def __init__(self, method, query=None, body=b""):
        self.method = method; self.query_params = query or {}; self._body = body
    async def body(self): return self._body


class DirectoryPluginTests(unittest.IsolatedAsyncioTestCase):
    async def test_upload_normalizes_thumbnail_and_catalog_exposes_revisioned_variant(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root); (path / "video.mp4").write_bytes(b"not needed for upload")
            source = DirectoryPluginSource(path, source_id="local")
            image = np.full((300, 300, 3), 127, dtype=np.uint8)
            ok, encoded = cv2.imencode(".jpg", image); self.assertTrue(ok)
            request = FakeRequest("POST", {"media_id":"video.mp4", "entry_type":"playable", "variant":"thumbnail"}, encoded.tobytes())
            result = await source.handle_host_action("previews/upload", request)
            self.assertTrue(result["updated"])
            target = path / ".previews" / "video_thumbnail.png"
            decoded = cv2.imread(str(target)); self.assertEqual((decoded.shape[1], decoded.shape[0]), (1280, 720))
            item = (await source.browse()).items[0]
            self.assertIsNotNone(item.thumbnail); self.assertIsNotNone(item.thumbnail.revision)


if __name__ == "__main__": unittest.main()
