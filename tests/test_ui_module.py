"""Prova que files/modules/ui.js escapa toda interpolacao.

O modulo usa template literal com `innerHTML`, escolha feita pela ergonomia.
Isso so e aceitavel porque a tag `html` escapa tudo que e interpolado --
e uma afirmacao que precisa de teste, nao de boa intencao.

O vetor nao e hipotetico: o rotulo de legenda e digitado por uma pessoa no
proprio painel, enviado ao backend e renderizado de volta.

A camada de string do modulo nao depende de DOM, entao roda em node.  Os
testes sao pulados quando node nao esta disponivel, para nao adicionar
dependencia obrigatoria a um projeto que roda com Python apenas.
"""

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
UI_MODULE = ROOT / "files" / "modules" / "ui.js"

NODE = shutil.which("node")


def run_in_node(body):
    """Executa `body` com o modulo importado como `ui`, devolvendo o JSON impresso.

    O arquivo e copiado para `.mjs` num diretorio temporario porque o node
    resolve `.js` sem package.json como CommonJS, e o modulo e ESM.  Copiar
    evita ter que renomear o arquivo ou adicionar um package.json ao repo
    so para satisfazer o executor de teste.
    """
    with TemporaryDirectory() as directory:
        module = Path(directory) / "ui.mjs"
        module.write_text(UI_MODULE.read_text(encoding="utf-8"), encoding="utf-8")
        script = Path(directory) / "case.mjs"
        script.write_text(
            f"import * as ui from './ui.mjs';\n{textwrap.dedent(body)}\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [NODE, str(script)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise AssertionError(f"node falhou: {result.stderr.strip()}")
        return json.loads(result.stdout.strip())


@unittest.skipUnless(NODE, "node nao disponivel")
class HtmlEscapingTests(unittest.TestCase):
    def test_interpolated_markup_is_neutralised(self):
        output = run_in_node(
            """
            const hostil = '<img src=x onerror="alert(1)">';
            console.log(JSON.stringify(ui.html`<p>${hostil}</p>`.value));
            """
        )
        # O texto sobrevive; o markup nao. `onerror=` continua presente como
        # texto literal inerte, e isso e o correto: escapar preserva o
        # conteudo digitado, apenas impede que ele vire elemento.
        self.assertNotIn("<img", output)
        self.assertIn("&lt;img", output)
        self.assertEqual(output.count("<"), output.count("<p>") + output.count("</p>"))

    def test_a_value_cannot_break_out_of_a_quoted_attribute(self):
        output = run_in_node(
            """
            const hostil = '" onmouseover="alert(1)';
            console.log(JSON.stringify(ui.html`<div title="${hostil}"></div>`.value));
            """
        )
        self.assertNotIn('onmouseover="alert(1)"', output)
        self.assertIn("&quot;", output)

    def test_a_subtitle_label_typed_by_a_person_is_safe_in_a_badge(self):
        """O caso real: rotulo digitado no painel volta do backend."""
        output = run_in_node(
            """
            const rotulo = '<script>alert(1)</scr' + 'ipt>';
            console.log(JSON.stringify(ui.badge({label: rotulo, tone: 'partial'}).value));
            """
        )
        self.assertNotIn("<script", output)
        self.assertIn("&lt;script", output)

    def test_technical_value_in_the_badge_title_is_escaped_too(self):
        output = run_in_node(
            """
            console.log(JSON.stringify(ui.badge({label: 'Parcial', technical: '" onload="x'}).value));
            """
        )
        self.assertNotIn('onload="x"', output)

    def test_arrays_escape_every_item(self):
        output = run_in_node(
            """
            console.log(JSON.stringify(ui.html`<ul>${['<b>a</b>', '<i>b</i>']}</ul>`.value));
            """
        )
        self.assertNotIn("<b>", output)
        self.assertNotIn("<i>", output)

    def test_nested_html_composes_without_double_escaping(self):
        output = run_in_node(
            """
            const inner = ui.html`<em>ok</em>`;
            console.log(JSON.stringify(ui.html`<p>${inner}</p>`.value));
            """
        )
        self.assertEqual(output, "<p><em>ok</em></p>")

    def test_raw_is_the_only_way_to_inject_markup(self):
        output = run_in_node(
            """
            console.log(JSON.stringify(ui.html`<p>${ui.raw('<em>ok</em>')}</p>`.value));
            """
        )
        self.assertEqual(output, "<p><em>ok</em></p>")

    def test_nullish_values_render_as_empty_not_as_the_word_null(self):
        output = run_in_node(
            """
            console.log(JSON.stringify(ui.html`<p>${null}${undefined}${false}</p>`.value));
            """
        )
        self.assertEqual(output, "<p></p>")


@unittest.skipUnless(NODE, "node nao disponivel")
class ComponentContractTests(unittest.TestCase):
    def test_a_disabled_button_always_carries_its_reason(self):
        """Botao morto sem explicacao e um dos defeitos que este redesign corrige."""
        output = run_in_node(
            """
            const markup = ui.button({label: 'Exportar', disabled: true, reason: 'Faltam segmentos'}).value;
            console.log(JSON.stringify(markup));
            """
        )
        self.assertIn("disabled", output)
        self.assertIn("aria-describedby=", output)
        self.assertIn("Faltam segmentos", output)

    def test_progress_is_clamped_and_announced(self):
        output = run_in_node(
            """
            console.log(JSON.stringify([
                ui.progressBar({value: 5, max: 1}).value,
                ui.progressBar({value: -3, max: 1}).value,
                ui.progressBar({value: 1, max: 4}).value,
            ]));
            """
        )
        self.assertIn('aria-valuenow="100"', output[0])
        self.assertIn("width:100%", output[0])
        self.assertIn('aria-valuenow="0"', output[1])
        self.assertIn('aria-valuenow="25"', output[2])

    def test_an_unknown_tone_falls_back_instead_of_emitting_a_dead_class(self):
        output = run_in_node(
            """
            console.log(JSON.stringify(ui.badge({label: 'x', tone: 'inventado'}).value));
            """
        )
        self.assertIn("ui-badge--neutral", output)

    def test_byte_formatting_matches_the_behaviour_it_replaces(self):
        output = run_in_node(
            """
            console.log(JSON.stringify([0, 512, 1024, 1536, 1073741824].map(ui.formatBytes)));
            """
        )
        self.assertEqual(output, ["0 B", "512 B", "1.00 KiB", "1.50 KiB", "1.00 GiB"])


@unittest.skipUnless(NODE, "node nao disponivel")
class StylesheetContractTests(unittest.TestCase):
    """Todo tom declarado no JS precisa existir no CSS, senao o badge sai sem cor."""

    def test_every_tone_has_a_matching_class(self):
        tones = run_in_node("console.log(JSON.stringify(ui.TONES));")
        css = (ROOT / "files" / "styles" / "components.css").read_text(encoding="utf-8")
        for tone in tones:
            with self.subTest(tone=tone):
                self.assertIn(f".ui-badge--{tone}", css)


if __name__ == "__main__":
    unittest.main()
