import os
import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path: sys.path.insert(0, SRC_DIR)

from media_sources import (ByteRangeRequest, InvalidByteRange, InvalidSourceConfiguration,
                           MediaItemNotFound, ResourceNotFound, build_source_registry)
from media_sources.plugins.directory.source_core import DirectorySource


async def collect(opened):
    return b"".join([chunk async for chunk in opened.chunks])


class RegistryTests(unittest.TestCase):
    def test_order_duplicates_and_disabled_sources(self):
        with tempfile.TemporaryDirectory() as root:
            registry = build_source_registry([
                {"id":"one","type":"directory","label":"One","options":{"path":root}},
                {"id":"off","type":"unknown","label":"Off","enabled":False,"options":{}},
            ])
            self.assertEqual([item.id for item in registry.summaries], ["one"])
            with self.assertRaises(InvalidSourceConfiguration):
                build_source_registry([
                    {"id":"one","type":"directory","label":"One","options":{"path":root}},
                    {"id":"one","type":"directory","label":"Two","options":{"path":root}},
                ])

    def test_unknown_and_invalid_plugin_sources_are_isolated(self):
        with tempfile.TemporaryDirectory() as root:
            empty = build_source_registry([]); self.assertEqual(empty.summaries, ())
            unknown = build_source_registry([{"id":"x","type":"unknown","label":"X","options":{}}])
            self.assertEqual(unknown.summaries, ()); self.assertIn("plugin ausente", unknown.diagnostics[0].message)
            invalid = build_source_registry([{"id":"x","type":"directory","label":"X","options":{"path":root,"private":1}}])
            self.assertEqual(invalid.summaries, ()); self.assertIn("InvalidSourceConfiguration", invalid.diagnostics[0].message)
            with self.assertRaises(InvalidSourceConfiguration): build_source_registry([{"id":"bad space","type":"directory","label":"X","options":{"path":root}}])


class DirectorySourceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / "Series").mkdir(); (self.root / "zeta.mp4").write_bytes(b"0123456789"); (self.root / "Alpha.mkv").write_bytes(b"abc")
        (self.root / ".hidden.mp4").write_bytes(b"hidden")
        (self.root / ".subs").mkdir(); (self.root / ".subs" / "zeta.pt.vtt").write_text("WEBVTT", encoding="utf-8")
        (self.root / ".subs" / "zeta 2.pt.vtt").write_text("WEBVTT", encoding="utf-8")
        (self.root / ".dubs").mkdir(); (self.root / ".dubs" / "zeta.en.mp3").write_bytes(b"audio")
        (self.root / ".previews").mkdir(); (self.root / ".previews" / "zeta_thumbnail.png").write_bytes(b"png")
        (self.root / "Series" / ".previews").mkdir(); (self.root / "Series" / ".previews" / "poster.png").write_bytes(b"png")
        self.source = DirectorySource(self.root)

    async def asyncTearDown(self): self.temp.cleanup()

    async def test_shallow_browse_orders_collections_then_playable(self):
        page = await self.source.browse()
        self.assertEqual([item.title for item in page.items], ["Series", "Alpha.mkv", "zeta.mp4"])
        self.assertEqual(page.items[0].entry_type.value, "collection")
        self.assertIsNotNone(page.items[0].poster)
        self.assertIsNotNone(page.items[-1].thumbnail)

    async def test_item_sidecars_respect_separator_and_resources_are_private(self):
        item = await self.source.get_item("zeta.mp4")
        self.assertEqual(len(item.subtitles), 1); self.assertEqual(len(item.audio_tracks), 1)
        with self.assertRaises(ResourceNotFound): await self.source.open_resource("../secret.mp4")
        (self.root / "notes.txt").write_text("private")
        with self.assertRaises(ResourceNotFound): await self.source.open_resource("notes.txt")
        with self.assertRaises(MediaItemNotFound): await self.source.get_item("missing.mp4")

    async def test_full_closed_open_and_suffix_ranges(self):
        full = await self.source.open_resource("zeta.mp4"); self.assertEqual(await collect(full), b"0123456789")
        closed = await self.source.open_resource("zeta.mp4", ByteRangeRequest(start=2, end=4)); self.assertEqual(await collect(closed), b"234")
        opened = await self.source.open_resource("zeta.mp4", ByteRangeRequest(start=7)); self.assertEqual(await collect(opened), b"789")
        suffix = await self.source.open_resource("zeta.mp4", ByteRangeRequest(suffix_length=3)); self.assertEqual(await collect(suffix), b"789")
        with self.assertRaises(InvalidByteRange): await self.source.open_resource("zeta.mp4", ByteRangeRequest(start=20))


if __name__ == "__main__": unittest.main()
