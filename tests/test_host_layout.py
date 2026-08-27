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
        self.assertNotIn('id="update-banners-btn"', html)
        self.assertNotIn('id="video-url-field"', html)
        self.assertIn("entry_type === 'collection' ? 'folder' : 'video'", javascript)
        self.assertIn(".media-item.folder img.banner", html)
        self.assertIn(".media-item.video img.banner", html)


if __name__ == "__main__":
    unittest.main()
