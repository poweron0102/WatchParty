import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _rule(stylesheet, selector):
    pattern = rf"{re.escape(selector)}\s*\{{(?P<body>[^}}]*)\}}"
    match = re.search(pattern, stylesheet)
    if not match:
        raise AssertionError(f"CSS rule not found: {selector}")
    return match.group("body")


class PartyLayoutRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = (ROOT / "files" / "chat" / "chat.css").read_text(encoding="utf-8")
        cls.javascript = (ROOT / "files" / "chat" / "chat.js").read_text(encoding="utf-8")

    def test_chat_history_is_the_only_growing_scroll_region(self):
        chat_box = _rule(self.css, "#chat-box")
        user_list = _rule(self.css, "#user-list")
        input_area = _rule(self.css, "#chat-input-area")
        sidebar = _rule(self.css, "#sidebar")

        self.assertRegex(chat_box, r"flex\s*:\s*1")
        self.assertRegex(chat_box, r"min-height\s*:\s*0")
        self.assertRegex(chat_box, r"overflow-y\s*:\s*auto")
        self.assertRegex(user_list, r"flex-shrink\s*:\s*0")
        self.assertRegex(input_area, r"flex-shrink\s*:\s*0")
        self.assertRegex(sidebar, r"overflow\s*:\s*hidden")

    def test_collapsed_state_resizes_the_chat_container(self):
        collapsed = _rule(self.css, "#chat-container.collapsed")
        self.assertRegex(collapsed, r"flex\s*:\s*0\s+0\s+0")
        self.assertRegex(collapsed, r"width\s*:\s*0")

        mobile_collapsed = re.search(
            r"#chat-container\.collapsed\s*\{(?P<body>[^}]*)\}",
            self.css[self.css.index("@media (max-width: 900px)"):],
        )
        self.assertIsNotNone(mobile_collapsed)
        self.assertRegex(mobile_collapsed.group("body"), r"flex-basis\s*:\s*48px")

    def test_javascript_toggles_container_state_without_inline_size_conflicts(self):
        self.assertIn("chatContainer.classList.toggle('collapsed')", self.javascript)
        self.assertIn("toggleBtn.setAttribute('aria-expanded'", self.javascript)
        self.assertNotIn("chatContainer.style.width", self.javascript)
        self.assertNotIn("chatContainer.style.flexBasis", self.javascript)


if __name__ == "__main__":
    unittest.main()
