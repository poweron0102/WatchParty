"""Regressoes de layout do Painel do Host.

Cada teste aqui existe porque um bug real aconteceu.  As asercoes miram na
*intencao* de cada regressao -- o card de pasta e vertical, o titulo do card
flutua sobre a imagem, a pagina nao rola inteira -- e nao na aparencia do
momento em que o bug foi corrigido.

Regra deste arquivo: nada de classe utilitaria, texto de interface ou string
literal de CSS.  Elemento se ancora em ``data-testid``; estilo se verifica por
propriedade.  Ver ``tests/ui_support.py``.
"""

import re
import unittest

from ui_support import ROOT, css_rule, element_ids, has_rule, page_css, read_page, read_script


class HostShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = read_page("host.html")
        cls.css = page_css("host.html")
        cls.javascript = read_script("host.js")
        cls.ids = element_ids(cls.html)

    def test_every_functional_anchor_of_the_panel_is_present(self):
        self.assertLessEqual(
            {
                "host-shell",
                "host-header",
                "source-select",
                "source-tools-button",
                "remote-admin-toggle",
                "catalog-search",
                "catalog-scroll",
                "video-grid",
                "folder-grid",
                "video-section-title",
                "folder-section-title",
                "tools-modal",
                "tools-modal-body",
                "inspector-modal",
                "inspector-favorite",
                "inspector-plugin-root",
            },
            self.ids,
        )

    def test_panel_no_longer_asks_for_a_raw_video_url(self):
        self.assertNotIn('id="video-url-field"', self.html)

    def test_plugin_extension_is_loaded_for_the_selected_source(self):
        self.assertIn("loadSourceExtension", self.javascript)


class HostScrollTests(unittest.TestCase):
    """A pagina nao rola: quem rola sao as regioes internas."""

    @classmethod
    def setUpClass(cls):
        cls.css = page_css("host.html")

    def test_the_document_itself_does_not_scroll(self):
        self.assertEqual(css_rule(self.css, "html").get("overflow"), "hidden")
        self.assertEqual(css_rule(self.css, "body").get("overflow"), "hidden")

    def test_the_shell_is_bound_to_the_viewport_height(self):
        height = css_rule(self.css, ".host-shell").get("height", "")
        self.assertRegex(height, r"100(dvh|vh)")

    def test_the_catalog_region_scrolls_on_its_own(self):
        self.assertEqual(css_rule(self.css, ".catalog-scroll").get("overflow-y"), "auto")
        self.assertEqual(css_rule(self.css, ".catalog-scroll").get("min-height"), "0")

    def test_scrollbars_are_styled_instead_of_browser_default(self):
        self.assertIn("scrollbar-color", css_rule(self.css, "*"))
        self.assertTrue(has_rule(self.css, "*::-webkit-scrollbar-thumb"))


class MediaCardTests(unittest.TestCase):
    """O card de pasta e retrato e o de video e paisagem -- nunca misturados."""

    @classmethod
    def setUpClass(cls):
        cls.css = page_css("host.html")
        cls.javascript = read_script("host.js")

    def test_folder_and_video_banners_keep_distinct_aspect_ratios(self):
        folder = css_rule(self.css, ".media-item.folder img.banner").get("aspect-ratio")
        video = css_rule(self.css, ".media-item.video img.banner").get("aspect-ratio")
        self.assertEqual(folder, "2/3")
        self.assertEqual(video, "16/9")
        self.assertNotEqual(folder, video)

    def test_the_card_class_follows_the_entity_type(self):
        self.assertRegex(self.javascript, r"entry_type\s*===\s*'collection'\s*\?\s*'folder'\s*:\s*'video'")

    def test_the_title_floats_over_the_banner(self):
        rule = css_rule(self.css, ".media-item .file-name")
        self.assertEqual(rule.get("position"), "absolute")
        self.assertEqual(rule.get("bottom"), "0")

    def test_the_title_overlay_is_translucent_and_follows_the_card_corners(self):
        rule = css_rule(self.css, ".media-item .file-name")
        background = rule.get("background-color") or rule.get("background") or ""
        self.assertRegex(
            background,
            r"(rgba|hsla|/\s*[\d.]+%?\s*\)|var\()",
            "o overlay do titulo precisa ser translucido para a capa aparecer atras",
        )
        self.assertIn("border-radius", rule)

    def test_grids_are_grids_so_cards_never_stretch_to_the_tallest_sibling(self):
        rule = css_rule(self.css, ".media-grid-layout")
        self.assertEqual(rule.get("display"), "grid")
        self.assertEqual(rule.get("align-items"), "start")


class CatalogSectionTests(unittest.TestCase):
    """Views agregadas nao podem rotular toda entidade como 'video'."""

    @classmethod
    def setUpClass(cls):
        cls.javascript = read_script("host.js")

    def test_section_titles_are_computed_not_hardcoded(self):
        self.assertRegex(self.javascript, r"videoSectionTitle\.textContent\s*=")
        self.assertRegex(self.javascript, r"folderSectionTitle\.textContent\s*=")

    def test_favorites_and_history_roots_drive_the_titles(self):
        self.assertRegex(self.javascript, r"\bfavoritesRoot\b")
        self.assertRegex(self.javascript, r"\bhistoryRoot\b")

    def test_navigating_into_a_favorite_collection_leaves_the_flat_view(self):
        routes = (ROOT / "src" / "http_routes.py").read_text(encoding="utf-8")
        self.assertRegex(
            routes,
            r'view in \{"history", "favorites"\}\s+and\s+parent_id is None',
        )


if __name__ == "__main__":
    unittest.main()
