import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HostLayoutRegressionTests(unittest.TestCase):
    def test_host_keeps_styled_shell_and_media_aspect_ratio_mapping(self):
        html = (ROOT / "files" / "host.html").read_text(encoding="utf-8")
        javascript = (ROOT / "files" / "host.js").read_text(encoding="utf-8")

        self.assertIn("container mx-auto p-4 md:p-8 max-w-7xl", html)
        self.assertIn("Gerencie sua sessão de Watch Party", html)
        self.assertIn("bg-card p-6 rounded-lg shadow-lg", html)
        self.assertIn('id="source-select"', html)
        self.assertIn('id="source-extension-root"', html)
        self.assertIn('id="remote-host-admin-toggle"', html)
        self.assertNotIn('id="video-url-field"', html)
        self.assertIn("entry_type === 'collection' ? 'folder' : 'video'", javascript)
        self.assertIn("loadSourceExtension", javascript)
        self.assertIn(".media-item.folder img.banner", html)
        self.assertIn(".media-item.video img.banner", html)

    def test_host_uses_internal_scroll_and_styled_scrollbars(self):
        html = (ROOT / "files" / "host.html").read_text(encoding="utf-8")
        self.assertIn("html,body{height:100%;overflow:hidden}", html)
        self.assertIn(".host-shell{height:100dvh", html)
        self.assertIn("scrollbar-color:", html)
        self.assertIn("::-webkit-scrollbar-thumb", html)

    def test_card_title_is_an_overlay_like_the_previous_layout(self):
        html = (ROOT / "files" / "host.html").read_text(encoding="utf-8")
        self.assertIn(".media-item .file-name{position:absolute;bottom:0", html)

    def test_card_overlay_preserves_old_transparency_and_rounded_corners(self):
        html = (ROOT / "files" / "host.html").read_text(encoding="utf-8")
        self.assertIn("background-color:rgba(30,30,30,.7)", html)
        self.assertIn("border-radius:0 0 .5rem .5rem", html)
        self.assertIn(".media-item img.banner{width:100%;object-fit:cover;display:block;border-radius:.5rem}", html)

    def test_favorites_do_not_mix_vertical_and_horizontal_cards_in_one_grid(self):
        html = (ROOT / "files" / "host.html").read_text(encoding="utf-8")
        javascript = (ROOT / "files" / "host.js").read_text(encoding="utf-8")
        self.assertIn(".media-grid-layout{display:grid;align-items:start", html)
        self.assertIn('id="folder-section-title"', html)
        self.assertIn("const favoritesRoot", javascript)
        self.assertIn("folderSectionTitle.textContent = favoritesRoot", javascript)
        self.assertIn("videoSectionTitle.textContent = historyRoot", javascript)

    def test_favorite_collection_navigation_leaves_the_flat_view(self):
        routes = (ROOT / "src" / "http_routes.py").read_text(encoding="utf-8")
        self.assertIn('if view in {"history", "favorites"} and parent_id is None:', routes)

    def test_single_views_do_not_label_every_entity_as_video(self):
        html = (ROOT / "files" / "host.html").read_text(encoding="utf-8")
        javascript = (ROOT / "files" / "host.js").read_text(encoding="utf-8")
        self.assertIn('id="video-section-title"', html)
        self.assertIn("videoSectionTitle.textContent", javascript)


if __name__ == "__main__":
    unittest.main()
