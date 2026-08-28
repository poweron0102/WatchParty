import asyncio
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path: sys.path.insert(0, SRC_DIR)

from playback import (OriginPresentation, OriginRepresentation, OriginSegment, OriginTrack,
                      PlaybackModule, PlaybackSelection, ResourceRequest, SegmentArtifact)
from playback.models import PlaybackExpired, PlaybackPaused
from playback.manifest import build_mpd
from media_sources.directory_playback import _split_fragmented_mp4


class FakeOrigin:
    def __init__(self, root): self.root, self.calls, self.inspections = Path(root), 0, 0
    async def inspect(self, media_id):
        self.inspections += 1; await asyncio.sleep(0.02)
        rep = OriginRepresentation("v1", 1000, "avc1.4d401e", "video/mp4", "init", (OriginSegment("s1", 0, 10),), 640, 360)
        return OriginPresentation(media_id, "Example", 10, (OriginTrack("video", "video", (rep,)),), "revision")
    async def materialize(self, media_id, demand):
        self.calls += 1; await asyncio.sleep(0.02)
        data = demand.segment_identity.encode(); path = self.root / f"{self.calls}.bin"; path.write_bytes(data)
        return SegmentArtifact(path, "video/mp4", len(data), hashlib.sha256(data).hexdigest())


class PlaybackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.origin = FakeOrigin(self.temp.name)
        self.module = PlaybackModule({"source": self.origin}, Path(self.temp.name) / "cache", wait_timeout=1)

    async def asyncTearDown(self): self.temp.cleanup()

    async def test_manifest_is_local_and_open_does_not_materialize(self):
        descriptor = await self.module.select(PlaybackSelection("source", "media"))
        opened = await self.module.open(descriptor.playback_id, "manifest.mpd", ResourceRequest())
        body = b"".join([chunk async for chunk in opened.chunks])
        self.assertIn(b"type=\"static\"", body); self.assertNotIn(b"http", body); self.assertEqual(self.origin.calls, 0)
        self.assertIn(b'<SegmentTimeline><S t="0" d="10000"/></SegmentTimeline>', body)

    async def test_single_flight_pause_and_expiration(self):
        descriptor = await self.module.select(PlaybackSelection("source", "media"))
        resource = next(iter(self.module._active.resources))
        first, second = await asyncio.gather(*(self.module.open(descriptor.playback_id, resource, ResourceRequest()) for _ in range(2)))
        self.assertEqual(self.origin.calls, 1); self.assertEqual(first.total_size, second.total_size)
        missing = list(self.module._active.resources)[1]
        await self.module.set_download_paused(descriptor.playback_id, True)
        with self.assertRaises(PlaybackPaused): await self.module.open(descriptor.playback_id, missing, ResourceRequest())
        self.origin.inspect = lambda media_id: _different(media_id)
        await self.module.select(PlaybackSelection("source", "other"))
        with self.assertRaises(PlaybackExpired): await self.module.open(descriptor.playback_id, resource, ResourceRequest())

    async def test_concurrent_selection_is_single_flight(self):
        first, second = await asyncio.gather(*(
            self.module.select(PlaybackSelection("source", "media")) for _ in range(2)))
        self.assertEqual(self.origin.inspections, 1)
        self.assertEqual(first.playback_id, second.playback_id)

    def test_directory_fmp4_is_split_between_init_and_media(self):
        def box(kind, payload=b""):
            return (8 + len(payload)).to_bytes(4, "big") + kind + payload
        init, media = _split_fragmented_mp4(box(b"ftyp") + box(b"moov") + box(b"moof") + box(b"mdat"))
        self.assertEqual(init[4:8], b"ftyp"); self.assertIn(b"moov", init); self.assertNotIn(b"moof", init)
        self.assertEqual(media[4:8], b"moof"); self.assertNotIn(b"moov", media)

    def test_text_track_uses_local_webvtt_resource(self):
        rep = OriginRepresentation("sub-pt", 1, "wvtt", "text/vtt", "subtitle", ())
        track = OriginTrack("subtitle:pt-br", "text", (rep,), "pt-BR", "Português")
        presentation = OriginPresentation("episode", "Example", 10, (track,), "revision")
        manifest = build_mpd(presentation, {("subtitle:pt-br", "sub-pt", "subtitle"): "/playback/id/asset/local"})
        self.assertIn(b'contentType="text" lang="pt-BR"', manifest)
        self.assertIn(b'<BaseURL>/playback/id/asset/local</BaseURL>', manifest)
        self.assertNotIn(b'<SegmentList', manifest)


async def _different(media_id):
    rep = OriginRepresentation("v", 1, "avc1", "video/mp4", "init", ())
    return OriginPresentation(media_id, "Other", 1, (OriginTrack("v", "video", (rep,)),), "other")


if __name__ == "__main__": unittest.main()
