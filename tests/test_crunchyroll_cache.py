import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path: sys.path.insert(0, SRC_DIR)

from media_sources.plugins.crunchyroll.cache import CrunchyrollCache
from media_sources.models import CatalogEntry, EntryType
from playback.models import (OriginPresentation, OriginRepresentation, OriginSegment, OriginTrack,
                             SegmentArtifact, SegmentDemand)


class CrunchyrollCacheTests(unittest.TestCase):
    def test_presentation_round_trip_supports_restart(self):
        with tempfile.TemporaryDirectory() as root:
            cache = CrunchyrollCache(root, "crunch")
            segments = (OriginSegment("s1", 0, 4.5), OriginSegment("s2", 4.5, 5.5))
            representation = OriginRepresentation(
                "v1080", 2, "avc1", "video/mp4", "init", segments, 1920, 1080)
            presentation = OriginPresentation(
                "episode:1", "Episode", 10,
                (OriginTrack("video", "video", (representation,), default=True),),
                "stable-revision", canonical_video_representation="v1080")

            cache.remember(presentation)
            restored = CrunchyrollCache(root, "crunch").load_presentation("episode:1")

            self.assertEqual(restored, presentation)

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


def cache_one_episode(cache, media_id, root):
    """Deixa `media_id` completo (video + audio) no cache."""
    timeline = (OriginSegment("s1", 0, 10),)
    video = OriginRepresentation("v1080", 2, "avc1", "video/mp4", "init", timeline, 1920, 1080)
    audio = OriginRepresentation("a-ja", 1, "mp4a", "audio/mp4", "init", timeline)
    cache.remember(OriginPresentation(
        media_id, media_id, 10,
        (OriginTrack("video", "video", (video,)), OriginTrack("audio-ja", "audio", (audio,), "ja-JP")),
        "revision", canonical_video_representation="v1080"))
    source = Path(root) / f"artifact-{media_id.replace(':', '-')}"
    source.write_bytes(b"segment")
    artifact = SegmentArtifact(source, "video/mp4", 7, hashlib.sha256(b"segment").hexdigest())
    for track, representation in (("video", "v1080"), ("audio-ja", "a-ja")):
        for identity in ("init", "s1"):
            cache.publish(media_id, SegmentDemand(track, representation, identity), artifact)


class CollectionSummaryTests(unittest.TestCase):
    """O agregado de uma serie tem que falar da serie aberta.

    O painel montava esse numero no navegador filtrando o inventario inteiro
    por ``media_id.startsWith('episode:')`` -- ou seja, contava os episodios
    de TODAS as series e exibia o total como se fosse o da entidade aberta.
    A hierarquia sempre esteve em ``catalog_edges``; o prefixo do id nunca
    soube quem e filho de quem.
    """

    def _two_series(self, root):
        cache = CrunchyrollCache(root, "crunch")
        for parent, children in (("series:a", ("episode:a1", "episode:a2")),
                                 ("series:b", ("episode:b1",))):
            cache.remember_catalog(parent, [
                CatalogEntry(child, child, EntryType.PLAYABLE, entity_kind="episode")
                for child in children
            ])
        return cache

    def test_the_aggregate_counts_only_the_episodes_of_the_open_collection(self):
        with tempfile.TemporaryDirectory() as root:
            cache = self._two_series(root)
            cache_one_episode(cache, "episode:b1", root)

            a = cache.collection_summary("series:a")
            b = cache.collection_summary("series:b")

            self.assertEqual(a["total"], 2)
            self.assertEqual(b["total"], 1)
            # O episodio baixado e da serie B e so pode aparecer nela.
            self.assertEqual(b["offline"], 1)
            self.assertEqual(a["offline"], 0)
            self.assertEqual(a["empty"], 2)

    def test_an_episode_never_touched_counts_as_without_cache_not_as_missing(self):
        with tempfile.TemporaryDirectory() as root:
            cache = self._two_series(root)
            summary = cache.collection_summary("series:a")
            self.assertEqual(summary["known"], 0)
            self.assertEqual(summary["empty"], summary["total"])
            self.assertEqual(sum(summary[key] for key in ("empty", "partial", "offline", "exported")),
                             summary["total"])

    def test_an_unknown_collection_is_empty_rather_than_an_error(self):
        with tempfile.TemporaryDirectory() as root:
            summary = CrunchyrollCache(root, "crunch").collection_summary("series:nao-existe")
            self.assertEqual(summary["total"], 0)
            self.assertEqual(summary["cached_bytes"], 0)

    def test_the_summary_agrees_with_the_full_inventory_about_the_same_media(self):
        """Duas telas nao podem discordar sobre o estado da mesma midia."""
        with tempfile.TemporaryDirectory() as root:
            cache = self._two_series(root)
            cache_one_episode(cache, "episode:b1", root)
            inventory = {item["media_id"]: item["state"] for item in cache.inventory()}
            self.assertEqual(inventory["episode:b1"], "offline")
            self.assertEqual(cache.collection_summary("series:b")["offline"], 1)


class OrphanCleanupTests(unittest.TestCase):
    def test_removing_orphans_reports_the_same_shape_as_any_other_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            cache = CrunchyrollCache(root, "crunch")
            (cache.segments / "orphan").write_bytes(b"1234")
            self.assertEqual(cache.orphan_preview()["media"], [])

            result = cache.remove_orphans()

            self.assertEqual(result["removed"], 1)
            self.assertEqual(result["skipped"], 0)
            # `bytes` e o que foi recuperado de verdade, nao o previsto.
            self.assertEqual(result["bytes"], 4)


class CardStateTests(unittest.TestCase):
    """`states()` alimenta o selo dos cards: uma consulta por pagina.

    Antes, saber se um episodio estava baixado exigia abrir o Inspetor um por
    um -- ou pedir `inventory()`, que monta faixas e representacoes de TODAS
    as midias para responder sobre algumas.
    """

    def test_it_answers_only_about_the_ids_asked_for(self):
        with tempfile.TemporaryDirectory() as root:
            cache = CrunchyrollCache(root, "crunch")
            cache_one_episode(cache, "episode:1", root)
            cache_one_episode(cache, "episode:2", root)

            states = cache.states(["episode:1"])

            self.assertEqual(set(states), {"episode:1"})
            self.assertEqual(states["episode:1"]["state"], "offline")

    def test_an_id_the_cache_never_saw_is_simply_absent(self):
        """Ausente e mais util que uma linha dizendo zero: quem pergunta ja
        sabe o que fazer com o silencio, e o card nao ganha selo."""
        with tempfile.TemporaryDirectory() as root:
            cache = CrunchyrollCache(root, "crunch")
            self.assertEqual(cache.states(["episode:nunca-visto"]), {})
            self.assertEqual(cache.states([]), {})

    def test_it_agrees_with_the_full_inventory(self):
        with tempfile.TemporaryDirectory() as root:
            cache = CrunchyrollCache(root, "crunch")
            cache_one_episode(cache, "episode:1", root)
            inventory = {item["media_id"]: item for item in cache.inventory()}
            states = cache.states(["episode:1"])
            self.assertEqual(states["episode:1"]["state"], inventory["episode:1"]["state"])
            self.assertEqual(states["episode:1"]["coverage"], inventory["episode:1"]["coverage"])
            self.assertEqual(states["episode:1"]["cached_bytes"], inventory["episode:1"]["cached_bytes"])


class ExportValidityTests(unittest.TestCase):
    """Presenca e integridade sao perguntas diferentes.

    O rotulo "Exportado" e consultado em lote, para uma pagina inteira de
    cards; conferir o SHA-256 ali significaria reler todo MP4 ja exportado.
    A integridade continua verificavel, mas sob demanda.
    """

    def _export_row(self, path, size, sha):
        return {"path": str(path), "size": size, "sha256": sha}

    def test_presence_check_accepts_a_file_that_is_there_with_the_right_size(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "video.mp4"
            target.write_bytes(b"conteudo")
            row = self._export_row(target, 8, hashlib.sha256(b"conteudo").hexdigest())
            self.assertTrue(CrunchyrollCache._valid_export(row))

    def test_presence_check_rejects_a_missing_or_truncated_file(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "video.mp4"
            row = self._export_row(target, 8, hashlib.sha256(b"conteudo").hexdigest())
            self.assertFalse(CrunchyrollCache._valid_export(row))
            target.write_bytes(b"curto")
            self.assertFalse(CrunchyrollCache._valid_export(row))

    def test_only_the_deep_check_notices_content_that_changed_without_resizing(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "video.mp4"
            target.write_bytes(b"corrompido")
            row = self._export_row(target, 10, hashlib.sha256(b"originalxx").hexdigest())
            self.assertTrue(CrunchyrollCache._valid_export(row), "mesmo tamanho passa na presenca")
            self.assertFalse(CrunchyrollCache.verify_export(row), "o hash e quem pega isto")
