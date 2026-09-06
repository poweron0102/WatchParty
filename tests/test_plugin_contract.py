"""Guarda o contrato host<->plugin descrito em docs/host-plugin-contract.md.

O modo de falha destas quatro adicoes e sempre o mesmo e sempre silencioso:
o plugin chama `context.algumaCoisa()`, o host nao fornece, e o painel morre
com um TypeError no console que ninguem esta olhando.  Nenhum teste de
backend pega isso, porque nada disso passa pelo servidor.

Entao o que se afirma aqui e a juncao: **todo `context.X` usado por um plugin
existe no contexto que o host monta**, e o contrato escrito descreve o que o
host realmente entrega.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST_JS = ROOT / "files" / "host.js"
HOST_HTML = ROOT / "files" / "host.html"
CONTRACT = ROOT / "docs" / "host-plugin-contract.md"
PLUGINS = ROOT / "src" / "media_sources" / "plugins"
PLUGIN_MODULES = sorted(PLUGINS.glob("*/host.mjs"))


def _balanced_object(text, start):
    """Fatia o objeto literal `{...}` que comeca em ou apos ``start``."""
    open_at = text.index("{", start)
    depth, index = 0, open_at
    while index < len(text):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[open_at:index + 1]
        index += 1
    raise AssertionError("objeto literal sem fechamento")


def _top_level(literal):
    """O interior do literal com tudo que estiver aninhado substituido por espaco.

    Sem isso, uma funcao passada como valor (``request: (a, b) => ...``)
    contribui com os proprios identificadores como se fossem chaves.
    """
    out, depth = [], 0
    for character in literal[1:-1]:
        if character in "{([":
            depth += 1
        elif character in "})]":
            depth -= 1
        out.append(character if depth == 0 else " ")
    return "".join(out)


def _keys(literal):
    """Chaves de um objeto literal: ``nome:`` e atalhos ``nome,``/``nome}``."""
    body = _top_level(literal)
    found = set(re.findall(r"(?:^|,)\s*([A-Za-z_$][\w$]*)\s*:", body))
    found.update(re.findall(r"(?:^|,)\s*([A-Za-z_$][\w$]*)\s*(?=,|$)", body))
    return found


def host_context_keys():
    """Chaves de cada contexto, por painel.

    Os dois sao montados espalhando `sharedContext()`, mas nao sao iguais:
    `refresh` e `navigate` so existem nas Ferramentas, `entity` so no
    Inspetor.  Comparar contra a uniao dos dois deixaria passar justamente o
    erro que interessa -- usar no Inspetor algo que so as Ferramentas tem.
    """
    source = HOST_JS.read_text(encoding="utf-8")
    shared_at = source.index("return", source.index("function sharedContext()"))
    shared = _keys(_balanced_object(source, shared_at))
    result = {}
    for panel, marker in (("mount", ".mount("), ("mountInspector", ".mountInspector(")):
        own = _keys(_balanced_object(source, source.index(marker) + len(marker)))
        # `...sharedContext()` sobra do spread; nao e uma chave do contexto.
        result[panel] = {key for key in shared | own if key != "sharedContext"}
    return result


def plugin_context_uses(source):
    """`context.X` usado por painel, separando o corpo de cada export.

    O que estiver fora dos dois (helpers no topo do arquivo) conta para os
    dois, porque pode ser chamado de qualquer um deles.
    """
    regions = {"mount": [], "mountInspector": [], "shared": []}
    current = "shared"
    for line in source.splitlines():
        match = re.match(r"export\s+(?:async\s+)?function\s+(\w+)", line)
        if match:
            current = match.group(1) if match.group(1) in regions else "shared"
        regions[current].append(line)
    found = {}
    for panel in ("mount", "mountInspector"):
        text = "\n".join(regions[panel] + regions["shared"])
        found[panel] = set(re.findall(r"\bcontext\.([A-Za-z_$][\w$]*)", text))
    return found


class ContextSurfaceTests(unittest.TestCase):
    def test_both_panels_receive_the_four_additions(self):
        """As quatro sao aditivas e valem para os dois paineis."""
        provided = host_context_keys()
        for panel, keys in provided.items():
            for name in ("setHeader", "notifyChanged", "confirm", "request", "showStatus", "source"):
                with self.subTest(panel=panel, name=name):
                    self.assertIn(name, keys)

    def test_each_panel_keeps_the_capability_that_is_only_its_own(self):
        provided = host_context_keys()
        self.assertIn("refresh", provided["mount"])
        self.assertIn("navigate", provided["mount"])
        self.assertIn("entity", provided["mountInspector"])
        self.assertNotIn("entity", provided["mount"])

    def test_every_context_call_a_plugin_makes_is_something_that_panel_provides(self):
        provided = host_context_keys()
        for module in PLUGIN_MODULES:
            used = plugin_context_uses(module.read_text(encoding="utf-8"))
            for panel, names in used.items():
                for name in sorted(names):
                    with self.subTest(plugin=module.parent.name, panel=panel, call=name):
                        self.assertIn(
                            name, provided[panel],
                            f"{module.parent.name} usa context.{name} em {panel}, que o host "
                            "nao monta nesse painel; isso vira TypeError na montagem",
                        )

    def test_the_contract_documents_what_the_host_actually_hands_over(self):
        """Contrato que descreve algo que o host nao entrega e pior que nenhum."""
        text = CONTRACT.read_text(encoding="utf-8")
        for name in ("setHeader", "notifyChanged", "confirm", "catalogRendered"):
            with self.subTest(name=name):
                self.assertIn(f"context.{name}" if name != "catalogRendered" else name, text)


def plugin_requested_actions(source):
    """Acoes que o plugin pede via ``context.request(...)``, sem query string.

    Interpolacao vira `*`: `jobs/${job.id}/pause` nao pode ser comparado
    literalmente, mas o prefixo ainda diz qual rota e.
    """
    found = set()
    for match in re.findall(r"""context\.request\(\s*['"`]([^'"`]*)['"`]""", source):
        found.add(match.split("?", 1)[0])
    for match in re.findall(r"""context\.request\(\s*`([^`]*)`""", source):
        found.add(re.sub(r"\$\{[^}]*\}", "*", match).split("?", 1)[0])
    return {action for action in found if action}


def backend_actions(path):
    """Acoes que o backend do plugin atende."""
    text = path.read_text(encoding="utf-8")
    exact = set(re.findall(r"""action == ["']([^"']+)["']""", text))
    for group in re.findall(r"""action in \{([^}]+)\}""", text):
        exact.update(re.findall(r"""["']([^"']+)["']""", group))
    prefixes = set(re.findall(r"""action\.startswith\(["']([^"']+)["']""", text))
    return exact, prefixes


class RequestedRouteTests(unittest.TestCase):
    """Toda acao que um plugin pede tem que existir no backend dele.

    O host encaminha `/host/{source_id}/{action}` as cegas: se o nome nao
    casar, o backend devolve 404 e o painel mostra "Acao da origem falhou"
    sem dizer qual.  Um typo em nome de rota nao tem outro guarda.
    """

    BACKENDS = {"crunchyroll": "source.py", "directory": "backend.py"}

    def test_every_action_a_plugin_requests_is_served_by_its_backend(self):
        for module in PLUGIN_MODULES:
            name = module.parent.name
            exact, prefixes = backend_actions(module.parent / self.BACKENDS[name])
            for action in sorted(plugin_requested_actions(module.read_text(encoding="utf-8"))):
                with self.subTest(plugin=name, action=action):
                    served = action in exact or any(action.startswith(prefix) for prefix in prefixes)
                    self.assertTrue(served, f"{name} pede '{action}', que o backend nao atende")

    def test_the_collection_summary_route_exists(self):
        exact, _ = backend_actions(PLUGINS / "crunchyroll" / "source.py")
        self.assertIn("cache/summary", exact)


class HierarchyTests(unittest.TestCase):
    """Parentesco vem do banco, nunca do prefixo do id.

    O agregado de serie/temporada era montado no navegador filtrando o
    inventario inteiro por ``media_id.startsWith('episode:')``: contava os
    episodios de TODAS as series e exibia o numero como se fosse o da
    entidade aberta.
    """

    def test_no_plugin_infers_parentage_from_an_id_prefix(self):
        for module in PLUGIN_MODULES:
            # Comentario que *descreve* o defeito nao e o defeito -- e a
            # explicacao de por que a rota existe.
            code = re.sub(r"//[^\n]*|/\*.*?\*/", " ", module.read_text(encoding="utf-8"), flags=re.S)
            with self.subTest(plugin=module.parent.name):
                # Busca manual: assertNotRegex despejaria o arquivo inteiro.
                if re.search(r"""startsWith\(\s*['"](episode|season|series|movie):""", code):
                    self.fail(
                        f"{module.parent.name} deduz parentesco do prefixo do id; "
                        "use cache/summary?parent_id=, que resolve a hierarquia no banco"
                    )


class CatalogRenderedDispatchTests(unittest.TestCase):
    """O hook existia dos dois lados e mesmo assim nunca disparava.

    O host so olhava o export do modulo; os dois plugins devolviam o hook de
    `mount()`.  A lista de midias das Ferramentas ficava congelada no que
    existia quando o modal abriu.
    """

    def test_the_hook_reaches_the_mounted_extensions_and_not_only_the_module(self):
        source = HOST_JS.read_text(encoding="utf-8")
        block = _balanced_object(source, source.index("function notifyCatalogRendered"))
        for level in ("sourceExtension", "toolsExtension", "inspectorExtension"):
            with self.subTest(level=level):
                self.assertIn(level, block)

    def test_plugins_implement_it_where_the_host_now_delivers(self):
        for module in PLUGIN_MODULES:
            with self.subTest(plugin=module.parent.name):
                self.assertIn("catalogRendered", module.read_text(encoding="utf-8"))


class NativeDialogTests(unittest.TestCase):
    def test_no_plugin_falls_back_to_the_browser_confirm(self):
        """`confirm()` nativo abre longe do contexto e nao diz o que se perde."""
        for module in PLUGIN_MODULES:
            with self.subTest(plugin=module.parent.name):
                self.assertNotRegex(
                    module.read_text(encoding="utf-8"),
                    r"(?<![\w.])confirm\s*\(",
                    "use context.confirm({title, body, danger})",
                )


class ModuleLoadingTests(unittest.TestCase):
    def test_the_host_script_is_loaded_as_a_module(self):
        """host.js passou a importar modules/ui.js.  Sem type="module" o
        import e erro de sintaxe e o painel inteiro nao inicia."""
        html = HOST_HTML.read_text(encoding="utf-8")
        self.assertRegex(html, r"""<script[^>]+type=["']module["'][^>]+src=["']host\.js""")

    def test_plugins_import_the_shared_module_by_absolute_path(self):
        """Servidos de /host/{id}/module.js, um caminho relativo erra o alvo."""
        for module in PLUGIN_MODULES:
            source = module.read_text(encoding="utf-8")
            if "modules/ui.js" not in source:
                continue
            with self.subTest(plugin=module.parent.name):
                self.assertIn("'/modules/ui.js'", source)


if __name__ == "__main__":
    unittest.main()
