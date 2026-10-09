"""Exercise the real asset handler through ASGI without loading saved credentials."""
import ast
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
import fastapi
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import StreamingResponse
from media_sources.errors import SourceReadError, SourceUnavailable, UpstreamUnavailable
from playback.models import (InvalidPlaybackResource, MaterializationTimeout, PlaybackExpired,
                             PlaybackNotFound, PlaybackPaused, ResourceRequest)


class PlaybackHttpTests(unittest.TestCase):
    def setUp(self):
        module = ast.parse((Path(__file__).resolve().parents[1] / 'src/http_routes.py').read_text(encoding='utf-8'))
        handler = next(n for n in module.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'playback_asset')
        handler.decorator_list = []
        self.playback = SimpleNamespace(open=AsyncMock())
        namespace = dict(globals(), PLAYBACK=self.playback)
        exec(compile(ast.Module(body=[handler], type_ignores=[]), 'src/http_routes.py', 'exec'), namespace)
        app = fastapi.FastAPI()
        app.add_api_route('/playback/{playback_id}/asset/{resource_id}', namespace['playback_asset'], methods=['GET', 'HEAD'])
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_source_failures_are_service_unavailable_for_get_and_head(self):
        for error in (SourceUnavailable('secret upstream URL'), SourceReadError('secret path')):
            for method in ('GET', 'HEAD'):
                with self.subTest(error=type(error).__name__, method=method):
                    self.playback.open.side_effect = error
                    response = self.client.request(method, '/playback/id/asset/segment')
                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(response.headers['Retry-After'], '1')
                    self.assertNotIn('secret', response.text)

    def test_existing_playback_errors_keep_their_status(self):
        for error, status in ((PlaybackExpired(), 410), (PlaybackNotFound(), 404),
                              (InvalidPlaybackResource(), 404), (PlaybackPaused(), 409),
                              (MaterializationTimeout(), 503)):
            with self.subTest(error=type(error).__name__):
                self.playback.open.side_effect = error
                self.assertEqual(self.client.get('/playback/id/asset/segment').status_code, status)

    def test_worker_retry_after_reaches_http_response(self):
        self.playback.open.side_effect = UpstreamUnavailable(status=420, retry_after=37, operation='segment')
        for method in ('GET', 'HEAD'):
            response = self.client.request(method, '/playback/id/asset/segment')
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.headers['Retry-After'], '37')
