"""Guarda o sistema de design unificado.

A aplicacao tinha tres conjuntos de tokens conflitantes -- um em party.css,
uma copia byte-a-byte dele embutida em host.html, e um vocabulario
completamente diferente em style.css.  Nada impedia que voltassem a
divergir, porque nada afirmava que eles deviam ser um so.

Estes testes existem para que a divergencia volte como falha vermelha e
nao como "por que o /host parece de outro app?".
"""

import os
import re
import sys
import unittest

from ui_support import FILES, page_css, read_page

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
os.chdir(ROOT)

from fastapi.testclient import TestClient  # noqa: E402
from server_setup import app  # noqa: E402
import http_routes  # noqa: F401,E402

PAGES = ("index.html", "party.html", "host.html")

#: Tokens que definem a identidade visual.  Se uma pagina redeclarar
#: qualquer um deles localmente, ela comecou a virar um app separado.
SHARED_TOKENS = (
    "--bg",
    "--panel",
    "--text",
    "--muted",
    "--line",
    "--accent",
    "--bg-primary",
    "--bg-secondary",
    "--text-primary",
    "--text-secondary",
    "--border-color",
    "--accent-color",
)


def _local_stylesheets(page):
    """Folhas de estilo proprias da pagina, excluindo as compartilhadas."""
    html = read_page(page)
    found = []
    for tag in re.findall(r"""<link[^>]+rel=["']?stylesheet["']?[^>]*>""", html, re.I):
        match = re.search(r"""href=["']([^"']+)["']""", tag, re.I)
        if not match:
            continue
        href = match.group(1)
        if href.startswith(("http://", "https://", "//")) or href.startswith("styles/"):
            continue
        path = FILES / href.split("?", 1)[0].lstrip("/")
        if path.is_file() and "vendor" not in path.parts:
            found.append(path)
    return found


class SharedTokenTests(unittest.TestCase):
    def test_every_page_loads_the_shared_tokens_and_base(self):
        for page in PAGES:
            with self.subTest(page=page):
                html = read_page(page)
                self.assertIn("styles/tokens.css", html)
                self.assertIn("styles/base.css", html)

    def test_no_page_redeclares_a_shared_token(self):
        """Um valor de token so pode nascer em tokens.css."""
        for page in PAGES:
            for stylesheet in [None] + _local_stylesheets(page):
                if stylesheet is None:
                    css = "\n".join(
                        re.findall(r"<style[^>]*>(.*?)</style>", read_page(page), re.S | re.I)
                    )
                    origin = f"{page} (<style> embutido)"
                else:
                    css = stylesheet.read_text(encoding="utf-8")
                    origin = stylesheet.name
                for token in SHARED_TOKENS:
                    with self.subTest(origin=origin, token=token):
                        # Busca manual em vez de assertNotRegex: esta ultima
                        # despeja a folha de estilo inteira na mensagem.
                        if re.search(rf"{re.escape(token)}\s*:", css):
                            self.fail(
                                f"{origin} redeclara {token}; "
                                "o valor pertence a styles/tokens.css"
                            )

    def test_state_colours_are_defined_and_distinct(self):
        """Cor de estado precisa significar estado -- e estados diferentes
        precisam de cores diferentes, senao o badge nao informa nada."""
        tokens = (FILES / "styles" / "tokens.css").read_text(encoding="utf-8")
        values = {}
        for name in ("empty", "partial", "cached", "exported"):
            match = re.search(rf"--state-{name}\s*:\s*([^;]+);", tokens)
            self.assertIsNotNone(match, f"--state-{name} nao definido")
            values[name] = match.group(1).strip()
        self.assertEqual(len(set(values.values())), len(values), f"estados com a mesma cor: {values}")

    def test_danger_is_reserved_and_not_aliased_by_a_state(self):
        tokens = (FILES / "styles" / "tokens.css").read_text(encoding="utf-8")
        self.assertNotRegex(
            tokens,
            r"--state-[a-z]+\s*:\s*var\(--danger\)",
            "vermelho e reservado a erro e acao destrutiva; se um estado normal "
            "o usar, ele para de avisar",
        )


class StaticServingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_the_shared_stylesheets_are_actually_served(self):
        for path in ("/styles/tokens.css", "/styles/base.css", "/styles/components.css"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn("css", response.headers.get("content-type", ""))


if __name__ == "__main__":
    unittest.main()
