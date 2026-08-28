import os
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(os.path.dirname(__file__)).parent


class _VideoParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.player_attributes = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "video" and attributes.get("id") == "player":
            self.player_attributes = attributes


class PartyHtmlTests(unittest.TestCase):
    def test_shaka_player_does_not_enable_native_controls(self):
        parser = _VideoParser()
        parser.feed((ROOT / "files" / "party.html").read_text(encoding="utf-8"))
        self.assertIsNotNone(parser.player_attributes)
        self.assertNotIn("controls", parser.player_attributes)


if __name__ == "__main__": unittest.main()
