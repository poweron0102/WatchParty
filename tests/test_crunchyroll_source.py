import os
import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path: sys.path.insert(0, SRC_DIR)

from media_sources.crunchyroll import CrunchyrollSource
from media_sources.models import EntryType


class FakeApi:
    def __init__(self): self.calls = []
    async def get(self, path, params=None):
        self.calls.append((path, params))
        if "/series/" in path:
            return {"data": [{"id": "season-id", "type": "season", "title": "Season 1", "images": {}}]}
        if "/seasons/" in path:
            return {"data": [{"id": "episode-id", "type": "episode", "title": "Episode 1",
                              "episode_number": 1, "images": {"thumbnail": [[{"source": "https://img.example/episode.jpg"}]]}}]}
        return {"data": [{"id": "series-id", "type": "series", "title": "Series",
                          "images": {"poster_tall": [[{"source": "https://img.example/poster.jpg"}]]}}]}


class CrunchyrollSourceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.api = FakeApi()
        self.source = CrunchyrollSource(Path(self.temp.name), "secret", "pt-BR", 24, api=self.api)

    async def asyncTearDown(self): self.temp.cleanup()

    async def test_series_season_episode_navigation_is_typed_and_acyclic(self):
        series = self.source._entries(await self.api.get("browse"))[0]
        self.assertEqual(series.id, "series:series-id"); self.assertIsNotNone(series.image)
        seasons = await self.source.browse(series.id)
        self.assertEqual(seasons.items[0].id, "season:season-id")
        episodes = await self.source.browse(seasons.items[0].id)
        self.assertEqual(episodes.items[0].id, "episode:episode-id")
        self.assertEqual(episodes.items[0].entry_type, EntryType.PLAYABLE)
        self.assertIsNotNone(episodes.items[0].image)
        self.assertIn("/series/series-id/seasons", self.api.calls[-2][0])
        self.assertIn("/seasons/season-id/episodes", self.api.calls[-1][0])


if __name__ == "__main__": unittest.main()
