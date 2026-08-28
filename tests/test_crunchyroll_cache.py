import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path: sys.path.insert(0, SRC_DIR)

from media_sources.plugins.crunchyroll.cache import CrunchyrollCache
from playback.models import (OriginPresentation, OriginRepresentation, OriginSegment, OriginTrack,
                             SegmentArtifact, SegmentDemand)


class CrunchyrollCacheTests(unittest.TestCase):
    def test_index_inventory_publish_and_filtered_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            cache = CrunchyrollCache(root, "crunch")
            low = OriginRepresentation("v480", 1, "avc1", "video/mp4", "init", (OriginSegment("s1", 0, 10),), 854, 480)
            high = OriginRepresentation("v1080", 2, "avc1", "video/mp4", "init", (OriginSegment("s1", 0, 10),), 1920, 1080)
            presentation = OriginPresentation("episode:1", "Episode", 10, (OriginTrack("video", "video", (low, high)),), "revision", canonical_video_representation="v1080")
            cache.remember(presentation)
            source = Path(root) / "artifact"; source.write_bytes(b"segment")
            digest = hashlib.sha256(b"segment").hexdigest(); artifact = SegmentArtifact(source, "video/mp4", 7, digest)
            demand = SegmentDemand("video", "v480", "s1")
            published = cache.publish("episode:1", demand, artifact)
            self.assertEqual(cache.locate("episode:1", demand).sha256, digest)
            inventory = cache.inventory()[0]
            self.assertEqual(inventory["cached_count"], 1); self.assertGreater(inventory["coverage"], 0)
            preview = cache.cleanup_preview({"mode":"quality", "height":480})
            self.assertEqual(preview["count"], 1)
            with cache.lease([published]):
                self.assertEqual(cache.cleanup({"mode":"quality", "height":480})["removed"], 0)
                self.assertTrue(published.path.exists())
            result = cache.cleanup({"mode":"quality", "height":480})
            self.assertEqual(result["removed"], 1); self.assertFalse(published.path.exists())

    def test_reconcile_removes_missing_rows_but_not_unknown_files(self):
        with tempfile.TemporaryDirectory() as root:
            cache = CrunchyrollCache(root, "crunch")
            orphan = cache.segments / "orphan"; orphan.write_bytes(b"x")
            cache.reconcile()
            self.assertTrue(orphan.exists()); self.assertEqual(cache.orphan_preview()["count"], 1)

    def test_database_cannot_be_shared_by_two_source_instances(self):
        with tempfile.TemporaryDirectory() as root:
            CrunchyrollCache(root, "primary")
            with self.assertRaisesRegex(RuntimeError, "outra instância"):
                CrunchyrollCache(root, "secondary")

    def test_partial_cleanup_preserves_complete_offline_selection(self):
        with tempfile.TemporaryDirectory() as root:
            cache = CrunchyrollCache(root, "crunch")
            timeline = (OriginSegment("s1", 0, 10),)
            video = OriginRepresentation("v1080", 2, "avc1", "video/mp4", "init", timeline, 1920, 1080)
            audio = OriginRepresentation("a-ja", 1, "mp4a", "audio/mp4", "init", timeline)
            presentation = OriginPresentation(
                "episode:1", "Episode", 10,
                (OriginTrack("video", "video", (video,)), OriginTrack("audio-ja", "audio", (audio,), "ja-JP")),
                "revision", canonical_video_representation="v1080")
            cache.remember(presentation)
            source = Path(root) / "artifact"; source.write_bytes(b"segment")
            digest = hashlib.sha256(b"segment").hexdigest()
            artifact = SegmentArtifact(source, "video/mp4", 7, digest)
            for track, representation in (("video", "v1080"), ("audio-ja", "a-ja")):
                for identity in ("init", "s1"):
                    cache.publish("episode:1", SegmentDemand(track, representation, identity), artifact)
            self.assertEqual(cache.inventory()[0]["state"], "offline")
            self.assertEqual(cache.cleanup_preview({"mode":"partial", "older_than_days":0})["count"], 0)
