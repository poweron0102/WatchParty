import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path: sys.path.insert(0, SRC_DIR)

from media_sources.crunchyroll_worker import CrunchyrollWorkerClient


class CrunchyrollWorkerClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_stream_accepts_large_presentation_messages(self):
        process = AsyncMock(); process.returncode = None
        process.stdout.readline.return_value = b""; process.stdin = AsyncMock()
        client = CrunchyrollWorkerClient("worker.exe", "secret", {})
        with patch("media_sources.crunchyroll_worker.asyncio.create_subprocess_exec", AsyncMock(return_value=process)) as create:
            with patch.object(client, "command", AsyncMock(return_value={})):
                await client._start()
                await asyncio.sleep(0)
        self.assertEqual(create.await_args.kwargs["limit"], 16 * 1024 * 1024)

    async def test_inspect_accepts_single_file_text_track_without_segments(self):
        client = CrunchyrollWorkerClient("worker.exe", "secret", {})
        result = {"presentation": {"title": "Episode", "duration": 10, "revision_seed": "rev", "tracks": [{
            "id": "subtitle:pt-br", "kind": "text", "language": "pt-BR", "representations": [{
                "id": "subtitle:pt-br:vtt", "bandwidth": 1, "codecs": "wvtt", "mime_type": "text/vtt",
                "initialization": "subtitle", "segments": None,
            }],
        }]}}
        with patch.object(client, "command", AsyncMock(return_value=result)):
            presentation = await client.inspect("episode")
        self.assertEqual(presentation.tracks[0].kind, "text")
        self.assertEqual(presentation.tracks[0].representations[0].segments, ())


if __name__ == "__main__": unittest.main()
