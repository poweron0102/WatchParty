import os
import sys
import tempfile
import unittest
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, patch

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path: sys.path.insert(0, SRC_DIR)

from media_sources.plugins.crunchyroll.catalog_core import CrunchyrollSource
from media_sources.plugins.crunchyroll.source import ManagedCrunchyrollSource
from media_sources.models import EntryType
from playback import PlaybackModule, PlaybackSelection, ResourceRequest
from playback.models import (OriginPresentation, OriginRepresentation, OriginSegment,
                             OriginTrack, SegmentArtifact, SegmentDemand)


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

    async def test_artwork_is_reused_from_disk_after_restart(self):
        resource = self.source._image_resource("https://img.example/poster.jpg")
        response = AsyncMock()
        response.content = b"image-bytes"
        response.headers = {"content-type": "image/jpeg"}
        response.raise_for_status = lambda: None
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.get.return_value = response

        with patch("media_sources.plugins.crunchyroll.catalog_core.httpx.AsyncClient", return_value=client):
            first = await self.source.open_resource(resource.id)
            self.assertEqual(b"".join([chunk async for chunk in first.chunks]), b"image-bytes")

        restarted = CrunchyrollSource(Path(self.temp.name), "secret", "pt-BR", 24, api=self.api)
        with patch("media_sources.plugins.crunchyroll.catalog_core.httpx.AsyncClient") as factory:
            second = await restarted.open_resource(resource.id)
            self.assertEqual(b"".join([chunk async for chunk in second.chunks]), b"image-bytes")
            factory.assert_not_called()

    async def test_managed_source_uses_cached_presentation_without_worker(self):
        source = ManagedCrunchyrollSource(
            "crunch", Path(self.temp.name), "secret", "pt-BR", 24,
            worker_path=None, worker_options={})
        representation = OriginRepresentation(
            "v1", 1, "avc1", "video/mp4", "init",
            (OriginSegment("s1", 0, 10),), 640, 360)
        expected = OriginPresentation(
            "episode:cached", "Cached", 10,
            (OriginTrack("video", "video", (representation,)),),
            "stable", canonical_video_representation="v1")
        source.cache.remember(expected)

        self.assertEqual(await source.inspect("episode:cached"), expected)

    async def test_complete_cached_playback_opens_without_worker(self):
        source = ManagedCrunchyrollSource(
            "crunch", Path(self.temp.name), "secret", "pt-BR", 24,
            worker_path=None, worker_options={})
        representation = OriginRepresentation(
            "v1", 1, "avc1", "video/mp4", "init",
            (OriginSegment("s1", 0, 10),), 640, 360)
        presentation = OriginPresentation(
            "episode:cached", "Cached", 10,
            (OriginTrack("video", "video", (representation,)),),
            "stable", canonical_video_representation="v1")
        source.cache.remember(presentation)
        for identity, data in (("init", b"clear-init"), ("s1", b"clear-media")):
            path = Path(self.temp.name) / identity
            path.write_bytes(data)
            source.cache.publish("episode:cached", SegmentDemand("video", "v1", identity),
                SegmentArtifact(path, "video/mp4", len(data), hashlib.sha256(data).hexdigest()))

        module = PlaybackModule({"crunch": source}, wait_timeout=1)
        descriptor = await module.select(PlaybackSelection("crunch", "episode:cached"))
        for resource_id in module._active.resources:
            opened = await module.open(descriptor.playback_id, resource_id, ResourceRequest())
            self.assertGreater(opened.content_length, 0)


if __name__ == "__main__": unittest.main()
