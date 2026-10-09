import asyncio
import io
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path: sys.path.insert(0, SRC_DIR)

from media_sources.plugins.crunchyroll.worker_client import CrunchyrollWorkerClient
from media_sources.errors import SourceUnavailable, UpstreamUnavailable


class CrunchyrollWorkerClientTests(unittest.IsolatedAsyncioTestCase):
    async def read_failure(self, extra):
        client = CrunchyrollWorkerClient('worker.exe', 'cookie-secret', {'private_key_path': 'private-secret.pem'})
        stream = asyncio.StreamReader()
        stream.feed_data((json.dumps({'request_id': 'request', 'event': 'failed', 'code': 'materialize_failed',
            'message': 'cookie-secret private-secret.pem https://cdn.example/?token=url-secret', **extra}) + '\n').encode())
        stream.feed_eof()
        client._process = SimpleNamespace(stdout=stream)
        future = asyncio.get_running_loop().create_future()
        client._pending['request'] = future
        client._pending_context['request'] = 'media=episode segment=sidx-16 priority=playback'
        output = io.StringIO()
        with patch('sys.stderr', output):
            await client._read()
        for secret in ('cookie-secret', 'private-secret.pem', 'url-secret'):
            self.assertNotIn(secret, output.getvalue())
        return future, output.getvalue()

    async def test_old_failure_event_remains_compatible(self):
        future, _ = await self.read_failure({})
        with self.assertRaises(SourceUnavailable): await future
        self.assertNotIsInstance(future.exception(), UpstreamUnavailable)

    async def test_structured_failure_preserves_metadata_and_safe_context(self):
        future, output = await self.read_failure({'status': 420, 'operation': 'segment', 'attempt': 5,
                                                'retry_after': 37, 'stage': 'download_media'})
        with self.assertRaises(UpstreamUnavailable) as raised: await future
        error = raised.exception
        self.assertEqual((error.status, error.operation, error.attempt, error.retry_after, error.stage),
                         (420, 'segment', 5, 37, 'download_media'))
        self.assertIn('segment=sidx-16', output)
        self.assertIn('stage=download_media', output)

    async def test_process_stream_accepts_large_presentation_messages(self):
        process = AsyncMock(); process.returncode = None
        process.stdout.readline.return_value = b""; process.stderr.readline.return_value = b""; process.stdin = AsyncMock()
        client = CrunchyrollWorkerClient("worker.exe", "secret", {})
        with patch("media_sources.plugins.crunchyroll.worker_client.asyncio.create_subprocess_exec", AsyncMock(return_value=process)) as create:
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
