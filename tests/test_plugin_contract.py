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


def plugin_regions(source, include_shared=True):
    """Corpo de cada export, separado.

    ``include_shared`` decide o que fazer com o que esta fora dos dois
    (helpers e tabelas no topo do arquivo).  Para saber o que um painel *pode
    chamar*, incluir e o certo -- qualquer um alcanca um helper.  Para saber
    o que um painel *oferece*, nao: a tabela de traducao cita 'download' como
    chave e nao e uma acao de ninguem.
    """
    regions = {"mount": [], "mountInspector": [], "shared": []}
    current = "shared"
    for line in source.splitlines():
        match = re.match(r"export\s+(?:async\s+)?function\s+(\w+)", line)
        if match:
            current = match.group(1) if match.group(1) in regions else "shared"
        regions[current].append(line)
    extra = regions["shared"] if include_shared else []
    return {panel: "\n".join(regions[panel] + extra) for panel in ("mount", "mountInspector")}


def plugin_context_uses(source):
    """`context.X` usado por painel."""
    return {panel: set(re.findall(r"\bcontext\.([A-Za-z_$][\w$]*)", text))
            for panel, text in plugin_regions(source).items()}


def quoted_strings(text):
    """Literais de string do trecho, para ver acoes passadas por variavel.

    `context.request(operation)` esconde o nome da rota; `start('download')`
    algumas linhas acima nao.
    """
    return set(re.findall(r"""['"]([^'"\n]{2,60})['"]""", text))


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


class ScopeSeparationTests(unittest.TestCase):
    """Uma ação pertence a UM dos dois painéis.

    A queixa que originou o redesign era redundância: Ferramentas e Inspetor
    ofereciam download, exportação e faixas com rótulos diferentes para as
    mesmas chamadas de backend.  Harmonizar os rótulos teria escondido o
    problema; o conserto foi separar por escopo.

    O `<select>` de mídia das Ferramentas era o que sustentava a duplicação --
    sem ele, operar uma mídia exige abrir a mídia.
    """

    #: Agem sobre UMA entidade: so o Inspetor.
    ENTITY_ACTIONS = ("download", "export-mp4", "download-export", "presentation", "subtitles/upload")

    #: Agem sobre a origem inteira: so as Ferramentas.
    GLOBAL_ACTIONS = ("preferences", "catalog/refresh", "cache/cleanup-preview")

    #: `cache/cleanup` e a excecao: a MESMA rota serve os dois escopos, e quem
    #: decide e o `mode` do payload.  Comparar pelo nome da rota daria um
    #: veredito errado nos dois sentidos, entao ela tem testes proprios.
    SCOPED_BY_PAYLOAD = {"cache/cleanup"}

    def _offered(self, module, panel):
        """Acoes que o painel oferece, inclusive as passadas por variavel.

        Comentario nao e oferta: o texto que *explica* os tres botoes antigos
        cita os rotulos deles, e sem descartar comentarios o teste leria isso
        como se o painel ainda os oferecesse.
        """
        source = re.sub(r"//[^\n]*|/\*.*?\*/", " ",
                        module.read_text(encoding="utf-8"), flags=re.S)
        body = plugin_regions(source, include_shared=False)[panel]
        return plugin_requested_actions(body) | quoted_strings(body)

    def test_the_tools_panel_does_not_operate_a_single_media(self):
        for module in PLUGIN_MODULES:
            offered = self._offered(module, "mount")
            for action in self.ENTITY_ACTIONS:
                with self.subTest(plugin=module.parent.name, action=action):
                    self.assertNotIn(
                        action, offered,
                        f"'{action}' age sobre uma entidade e pertence ao Inspetor",
                    )

    def test_the_inspector_does_not_administer_the_whole_source(self):
        for module in PLUGIN_MODULES:
            offered = self._offered(module, "mountInspector")
            for action in self.GLOBAL_ACTIONS:
                with self.subTest(plugin=module.parent.name, action=action):
                    self.assertNotIn(
                        action, offered,
                        f"'{action}' age sobre a origem inteira e pertence às Ferramentas",
                    )

    def test_the_media_picker_that_sustained_the_duplication_is_gone(self):
        """Sem o `<select>` de mídia, as Ferramentas não têm sobre o que agir."""
        body = plugin_regions(
            (PLUGINS / "crunchyroll" / "host.mjs").read_text(encoding="utf-8"),
            include_shared=False,
        )["mount"]
        self.assertNotIn("populateMedia", body)
        self.assertNotIn("mediaSelect", body)

    def test_no_action_is_offered_by_both_panels(self):
        """A definição operacional de "sem redundância"."""
        for module in PLUGIN_MODULES:
            source = module.read_text(encoding="utf-8")
            regions = plugin_regions(source)
            # Leitura de estado nao e acao: os dois paineis legitimamente
            # perguntam "como esta isto agora?", e `cache/states` ainda por
            # cima mora no hook de modulo, que conta para os dois.
            readonly = {"cache", "jobs", "cache/summary", "cache/states"}
            tools = plugin_requested_actions(regions["mount"]) - readonly - self.SCOPED_BY_PAYLOAD
            inspector = plugin_requested_actions(regions["mountInspector"]) - readonly - self.SCOPED_BY_PAYLOAD
            shared = {action for action in tools & inspector if not action.startswith("jobs/")}
            with self.subTest(plugin=module.parent.name):
                self.assertEqual(shared, set(), f"ação oferecida nos dois painéis: {sorted(shared)}")

    def test_the_two_panels_clean_up_at_different_scopes(self):
        """A mesma rota, escopos distintos -- e o payload que separa.

        Se as Ferramentas voltarem a oferecer o modo por mídia, volta o
        seletor de mídia, e com ele a redundância inteira.
        """
        source = re.sub(r"//[^\n]*|/\*.*?\*/", " ",
                        (PLUGINS / "crunchyroll" / "host.mjs").read_text(encoding="utf-8"), flags=re.S)
        modes = re.search(r"CLEANUP_MODES\s*=\s*\[(.*?)\];", source, re.S)
        self.assertIsNotNone(modes, "a lista de modos das Ferramentas sumiu")
        self.assertNotIn("'media'", modes.group(1),
                         "limpar UMA mídia é ação de entidade e pertence ao Inspetor")

        inspector = plugin_regions(source, include_shared=False)["mountInspector"]
        self.assertRegex(inspector, r"mode:\s*'media'",
                         "o Inspetor precisa limpar o cache no escopo da mídia aberta")


class CollapsedActionTests(unittest.TestCase):
    """Três ações concorrentes viraram um botão e uma caixa.

    `download`, `export-mp4` e `download-export` eram três botões para duas
    decisões.  Exportar não é uma terceira operação, é um sufixo do download --
    o backend já trata assim, porque `export-mp4` completa os segmentos que
    faltam apesar do nome.  A UI passou a dizer isso em vez de escondê-lo.
    """

    def setUp(self):
        self.source = re.sub(
            r"//[^\n]*|/\*.*?\*/", " ",
            (PLUGINS / "crunchyroll" / "host.mjs").read_text(encoding="utf-8"), flags=re.S)
        self.inspector = plugin_regions(self.source, include_shared=False)["mountInspector"]

    def test_the_ui_never_asks_for_export_as_a_separate_operation(self):
        """`export-mp4` continua no backend; deixa de ser um conceito na tela."""
        self.assertNotRegex(
            self.inspector, r"""['"]export-mp4['"]""",
            "exportar é sufixo de download: use download-export",
        )

    def test_the_choice_is_a_checkbox_and_the_operation_follows_it(self):
        self.assertRegex(self.inspector, r"type=\"checkbox\"[^>]*data-ref=\"exportToo\"")
        self.assertRegex(
            self.inspector,
            r"exportToo\.checked\s*\?\s*'download-export'\s*:\s*'download'",
            "a caixa é o que decide entre as duas operações do backend",
        )

    def test_the_button_explains_itself_instead_of_lying(self):
        """Um rótulo curto sobre estado que muda precisa de uma linha que diga
        o que o clique vai fazer agora."""
        self.assertIn("syncIntent", self.inspector)
        self.assertRegex(self.inspector, r"view\.exportToo\.onchange\s*=\s*syncIntent")


class DecorateCardTests(unittest.TestCase):
    """O estado de cache aparece no card, sem uma requisição por card.

    O hook existia e estava ocioso no host desde sempre; descobrir se um
    episódio estava baixado exigia abrir o Inspetor um por um.
    """

    def setUp(self):
        self.source = (PLUGINS / "crunchyroll" / "host.mjs").read_text(encoding="utf-8")

    def test_the_plugin_exports_the_hook_at_the_level_the_host_calls_it(self):
        """`decorateCard` é lido de `sourceExtension`, o export do módulo --
        devolvê-lo de `mount()` é o erro que deixou `catalogRendered` morto."""
        self.assertRegex(self.source, r"export\s+function\s+decorateCard")
        self.assertRegex(self.source, r"export\s+async\s+function\s+catalogRendered")

    def test_the_host_hands_the_page_hooks_a_way_to_make_requests(self):
        host = HOST_JS.read_text(encoding="utf-8")
        self.assertRegex(host, r"decorateCard\?\.\([^)]*pluginPage\)")
        self.assertRegex(host, r"catalogRendered\?\.\(state,\s*pluginPage\)")

    def _hook_body(self, name):
        match = re.search(rf"export (?:async )?function {name}\b.*?\n}}", self.source, re.S)
        self.assertIsNotNone(match, f"{name} sumiu")
        return match.group(0)

    def test_the_page_is_resolved_in_one_request_not_one_per_card(self):
        """Um selo por card não pode custar uma consulta por card.

        `decorateCard` roda durante a renderização, antes de o plugin saber
        qual é a página; por isso ele só cria o slot, e `catalogRendered`
        resolve a página inteira de uma vez.
        """
        self.assertNotIn("request", self._hook_body("decorateCard"))
        self.assertEqual(len(re.findall(r"context\.request\(", self._hook_body("catalogRendered"))), 1)

    def test_a_card_without_cache_gets_no_badge(self):
        """"Sem cache" em cada card de uma página inteira é ruído, não sinal."""
        self.assertRegex(self._hook_body("catalogRendered"), r"state\s*===\s*'empty'")


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
