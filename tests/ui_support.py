"""Ancoras estaveis para os testes de interface.

Testes de layout nao devem afirmar strings literais de CSS nem classes
utilitarias.  Uma asercao como ``"container mx-auto p-4 md:p-8 max-w-7xl"``
nao protege nada: ela apenas documenta o layout de ontem e transforma
qualquer melhoria visual em falha vermelha.  Pior, ela molda o produto --
``files/host.html`` chegou a carregar um comentario HTML existente apenas
para satisfazer um teste.

Este modulo oferece dois tipos de ancora que sobrevivem a um redesign mas
continuam pegando regressao de verdade:

``element_ids(html)``
    O elemento funcional continua existindo?  Ancorado em ``data-testid``,
    que so muda quando a funcao muda -- ao contrario de classes de estilo.

``css_rule(css, selector)``
    A regra continua declarando a propriedade que importa?  Compara
    propriedades, nao texto, entao sobrevive a reformatacao, minificacao,
    troca de cor e mudanca de ordem das declaracoes.

``page_css`` resolve tanto o ``<style>`` embutido quanto as folhas locais
ligadas pela pagina, de modo que mover CSS de dentro do HTML para um
arquivo proprio nao quebra teste algum.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / "files"


def read_page(name):
    """Devolve o HTML de uma pagina em ``files/``."""
    return (FILES / name).read_text(encoding="utf-8")


def read_script(name):
    """Devolve o conteudo de um script em ``files/``."""
    return (FILES / name).read_text(encoding="utf-8")


def page_css(name):
    """Todo o CSS que a pagina aplica: ``<style>`` embutido e folhas locais.

    Folhas remotas (fontes, CDN) sao ignoradas -- os testes nao devem
    depender de rede.
    """
    html = read_page(name)
    parts = re.findall(r"<style[^>]*>(.*?)</style>", html, re.S | re.I)
    for href in re.findall(r"""<link[^>]+rel=["']?stylesheet["']?[^>]*>""", html, re.I):
        match = re.search(r"""href=["']([^"']+)["']""", href, re.I)
        if not match or match.group(1).startswith(("http://", "https://", "//")):
            continue
        stylesheet = FILES / match.group(1).split("?", 1)[0].lstrip("/")
        if stylesheet.is_file():
            parts.append(stylesheet.read_text(encoding="utf-8"))
    return "\n".join(parts)


def element_ids(html):
    """Conjunto dos valores de ``data-testid`` presentes no HTML.

    Nao se chama ``test_ids`` porque o pytest coletaria a propria funcao
    auxiliar como caso de teste.
    """
    return set(re.findall(r"""data-testid=["']([^"']+)["']""", html))


def _strip_comments(css):
    return re.sub(r"/\*.*?\*/", " ", css, flags=re.S)


def _strip_at_rules(css):
    """Remove blocos ``@media``/``@supports`` para que a consulta veja a regra base.

    Uma regra dentro de media query e uma sobrescrita condicional; afirmar
    sobre ela por engano produz teste que passa pelo motivo errado.
    """
    out, index = [], 0
    while index < len(css):
        at = css.find("@", index)
        if at == -1:
            out.append(css[index:])
            break
        out.append(css[index:at])
        brace = css.find("{", at)
        semicolon = css.find(";", at)
        if brace == -1 or (semicolon != -1 and semicolon < brace):
            index = (semicolon + 1) if semicolon != -1 else len(css)
            continue
        depth, cursor = 0, brace
        while cursor < len(css):
            if css[cursor] == "{":
                depth += 1
            elif css[cursor] == "}":
                depth -= 1
                if depth == 0:
                    break
            cursor += 1
        index = cursor + 1
    return "".join(out)


def _normalize_selector(selector):
    selector = re.sub(r"\s+", " ", selector).strip()
    return re.sub(r"\s*([>+~,])\s*", r"\1", selector)


def _iter_rules(css):
    css = _strip_at_rules(_strip_comments(css))
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selectors = [
            _normalize_selector(part)
            for part in match.group(1).split(",")
            if part.strip()
        ]
        yield selectors, match.group(2)


def _declarations(body):
    result = {}
    for item in body.split(";"):
        if ":" not in item:
            continue
        prop, _, value = item.partition(":")
        result[prop.strip().lower()] = re.sub(r"\s+", " ", value).strip()
    return result


def css_rule(css, selector):
    """Declaracoes da regra ``selector``, mescladas na ordem em que aparecem.

    Encontra o seletor mesmo quando ele faz parte de um grupo
    (``.a,.b{...}``).  Levanta ``AssertionError`` quando a regra nao existe,
    para que a falha diga qual seletor sumiu.
    """
    wanted = _normalize_selector(selector)
    merged, found = {}, False
    for selectors, body in _iter_rules(css):
        if wanted in selectors:
            found = True
            merged.update(_declarations(body))
    if not found:
        raise AssertionError(f"Regra CSS ausente: {selector}")
    return merged


def has_rule(css, selector):
    """Se existe alguma regra para ``selector``, sem exigir declaracoes."""
    wanted = _normalize_selector(selector)
    return any(wanted in selectors for selectors, _ in _iter_rules(css))
