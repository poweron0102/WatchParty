"""Real catalog responses must include saved progress outside History view."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from fastapi.testclient import TestClient
import http_routes
from host_store import HostStore
from media_sources import build_source_registry
from server_setup import app


class CatalogHistoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        media = root / 'media'
        (media / 'season').mkdir(parents=True)
        (media / 'season' / 'episode.mp4').write_bytes(b'catalog fixture')
        self.store = HostStore(root / 'history.sqlite3')
        self.store.record_play('local', 'season/episode.mp4', 'video', title='episode',
                               position=120, duration=600)
        self.store.set_favorite('local', 'season/episode.mp4', 'video', title='episode')
        registry = build_source_registry([
            {'id':'local', 'type':'directory', 'label':'Local', 'options':{'path':str(media)}}])
        for name, value in [('MEDIA_SOURCES', registry), ('host_store', self.store)]:
            mocked = patch.object(http_routes, name, value)
            mocked.start()
            self.addCleanup(mocked.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def assert_progress(self, response):
        self.assertEqual(response.status_code, 200)
        item = next(item for item in response.json()['items'] if item['id'] == 'season/episode.mp4')
        self.assertIn('history', item, 'saved progress is missing from the real catalog response')
        self.assertEqual(item['history']['position'], 120)
        self.assertEqual(item['history']['duration'], 600)
        self.assertFalse(item['history']['completed'])

    def test_browsing_a_season_includes_saved_progress(self):
        self.assert_progress(self.client.get('/api/catalog', params={'source_id':'local', 'parent_id':'season'}))

    def test_browsing_inside_favorites_includes_saved_progress(self):
        self.assert_progress(self.client.get('/api/catalog', params={
            'source_id':'local', 'parent_id':'season', 'view':'favorites'}))

    def test_favorites_root_includes_saved_progress(self):
        self.assert_progress(self.client.get('/api/catalog', params={'source_id':'local', 'view':'favorites'}))

    def test_search_includes_saved_progress(self):
        self.assert_progress(self.client.get('/api/search', params={'source_id':'local', 'q':'episode'}))

    def test_history_view_keeps_saved_progress(self):
        self.assert_progress(self.client.get('/api/catalog', params={'source_id':'local', 'view':'history'}))

    def test_another_sources_history_does_not_mark_unwatched_media(self):
        self.store.clear_history('local')
        self.store.record_play('other', 'season/episode.mp4', 'video', title='episode', position=500, duration=600)
        result = self.client.get('/api/catalog', params={'source_id':'local', 'parent_id':'season'})
        self.assertEqual(result.status_code, 200)
        self.assertNotIn('history', result.json()['items'][0])
