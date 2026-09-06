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


#: Prefixos de classe que o projeto reconhece como vocabulario proprio.
#: `ui-` sao os componentes compartilhados, `plugin-` os agrupamentos que os
#: plugins montam, o resto e do painel do host.
CLASS_PREFIXES = ("host-", "catalog-", "media-", "ui-", "plugin-")

#: Classes sem prefixo que sobreviveram por serem estado ou papel dentro de um
#: componente ja prefixado (`.media-item.folder`, `.favorite-badge.is-favorite`).
BARE_CLASSES = {
    "banner", "file-name", "type-indicator", "favorite-badge",
    "folder", "video", "active", "is-favorite", "is-busy",
}

PLUGINS = FILES.parent / "src" / "media_sources" / "plugins"

#: Onde o Tailwind vivia.  Estes sao os arquivos cujo markup ele ditava.
MARKUP_SOURCES = (
    FILES / "host.html",
    FILES / "host.js",
    PLUGINS / "directory" / "host.mjs",
    PLUGINS / "crunchyroll" / "host.mjs",
)


def _class_tokens(text):
    """Classes citadas em ``class="..."``, ``className = '...'`` e ``el(..., '...')``.

    Interpolacoes (``${...}``) sao descartadas: o texto ao redor delas ja
    aparece como token proprio, e o valor injetado e estado, nao classe nova.
    """
    text = re.sub(r"\$\{[^{}]*\}", " ", text)
    found = set()
    for pattern in (
        r"""class=["']([^"']*)["']""",
        r"""className\s*=\s*['"`]([^'"`]*)['"`]""",
        r"""\bel\([^,]+,[^,]+,\s*'([^']*)'\s*\)""",
    ):
        for match in re.findall(pattern, text):
            found.update(match.split())
    return {token for token in found if token}


class NoUtilityFrameworkTests(unittest.TestCase):
    """O Tailwind saiu, e a forma de ele voltar tambem.

    Ele entrava por tres portas: o <script> do CDN, as classes-ponte que
    traduziam `bg-card` de volta para `var(--panel)`, e as strings de classe
    utilitaria espalhadas pelo markup.  Um teste por porta.
    """

    def test_no_page_loads_a_css_framework_from_a_cdn(self):
        for page in PAGES:
            with self.subTest(page=page):
                html = read_page(page)
                self.assertNotRegex(
                    html,
                    r"(?i)<script[^>]+src=[\"'][^\"']*tailwind",
                    "o CDN do Tailwind foi removido na etapa 5; estilo do projeto "
                    "mora em styles/",
                )

    def test_no_bridge_class_translates_a_framework_name_back_into_a_token(self):
        """`.bg-card{background:var(--panel)}` e sintoma de framework meio fora."""
        for page in PAGES:
            with self.subTest(page=page):
                for name in ("bg-card", "bg-brand", "bg-input", "border-input"):
                    self.assertNotIn(f".{name}", page_css(page))

    def test_every_class_in_the_host_markup_belongs_to_the_project_vocabulary(self):
        for path in MARKUP_SOURCES:
            for token in sorted(_class_tokens(path.read_text(encoding="utf-8"))):
                if token in BARE_CLASSES or token.startswith(CLASS_PREFIXES):
                    continue
                with self.subTest(origin=path.name, klass=token):
                    self.fail(
                        f"{path.name} usa a classe '{token}', que nao pertence ao "
                        f"vocabulario do projeto ({', '.join(CLASS_PREFIXES)}). "
                        "Classe de layout solta e como as utilitarias voltam."
                    )


    def test_every_class_used_in_the_host_actually_has_a_rule(self):
        """Sem o Tailwind, uma classe sem regra nao estiliza nada -- e falha
        em silencio, que e o modo de falha mais caro de descobrir."""
        css = re.sub(r"/\*.*?\*/", " ", page_css("host.html"), flags=re.S)
        defined = set(re.findall(r"\.([A-Za-z0-9_-]+)", css))
        used = set()
        for path in MARKUP_SOURCES:
            used.update(_class_tokens(path.read_text(encoding="utf-8")))
        for token in sorted(used):
            # Sobra de interpolacao: `host-status--${...}` vira o prefixo solto.
            if token.endswith("--"):
                continue
            with self.subTest(klass=token):
                self.assertIn(token, defined, f"a classe '{token}' nao tem regra em styles/")


class SharedUiModuleTests(unittest.TestCase):
    def test_plugins_import_the_shared_ui_instead_of_copying_a_button_factory(self):
        """A fabrica `button()` estava copiada byte-a-byte entre os plugins."""
        source = (PLUGINS / "directory" / "host.mjs").read_text(encoding="utf-8")
        self.assertRegex(
            source,
            r"""import\s*\{[^}]*\}\s*from\s*['"]/modules/ui\.js['"]""",
            "o modulo do plugin e servido de /host/{id}/module.js, entao o "
            "import precisa ser absoluto",
        )


class StaticServingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_the_shared_stylesheets_are_actually_served(self):
        for path in ("/styles/tokens.css", "/styles/base.css", "/styles/components.css", "/styles/host.css"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn("css", response.headers.get("content-type", ""))


if __name__ == "__main__":
    unittest.main()
