/* Primitivos de interface compartilhados pelo painel do host e pelos plugins.
 *
 * Por que este modulo existe
 * --------------------------
 * A UI dos plugins era montada com `document.createElement` linha a linha, e
 * a fabrica de botao estava copiada byte-a-byte entre os dois plugins, com a
 * mesma string de classes.  Toda consistencia visual dependia de alguem
 * lembrar de repetir o mesmo trecho.
 *
 * Escape nao e opcional
 * ---------------------
 * A tag `html` escapa TODA interpolacao.  Isso nao e paranoia sobre dados do
 * Crunchyroll: o rotulo de legenda e digitado por uma pessoa no proprio
 * painel, vai para o backend e volta para ser renderizado.  Com `innerHTML`
 * cru, `<img src=x onerror=...>` num rotulo executaria no painel do host.
 *
 * Para inserir HTML ja confiavel (tipicamente o resultado de outro `html`),
 * use `raw()` -- que existe justamente para que a excecao seja visivel na
 * leitura do codigo, em vez de implicita.
 *
 * Regra ao escrever templates: sempre use aspas nos atributos.
 * `<div class="${x}">` e seguro; `<div class=${x}>` nao e, porque um valor
 * com espaco escaparia do atributo.
 */

const RAW = Symbol('html-confiavel');

class Html {
    constructor(value) {
        this.value = value;
        this[RAW] = true;
    }
    toString() {
        return this.value;
    }
}

const ENTITIES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

/** Escapa texto para interpolacao segura em conteudo ou atributo aspeado. */
export function escapeHtml(value) {
    if (value == null) return '';
    return String(value).replace(/[&<>"']/g, character => ENTITIES[character]);
}

/** Marca uma string como HTML ja confiavel, dispensando o escape. */
export function raw(value) {
    return new Html(value == null ? '' : String(value));
}

export function isHtml(value) {
    return value instanceof Html || (value != null && value[RAW] === true);
}

function interpolate(value) {
    if (value == null || value === false || value === true) return '';
    if (isHtml(value)) return value.value;
    if (Array.isArray(value)) return value.map(interpolate).join('');
    return escapeHtml(value);
}

/** Template de HTML com escape automatico de toda interpolacao. */
export function html(strings, ...values) {
    let out = strings[0];
    for (let index = 0; index < values.length; index++) {
        out += interpolate(values[index]) + strings[index + 1];
    }
    return new Html(out);
}

/* --------------------------------------------------------------------- */
/* Renderizacao                                                           */
/* --------------------------------------------------------------------- */

/** Converte HTML confiavel num fragmento de DOM. */
export function toFragment(content) {
    const template = document.createElement('template');
    template.innerHTML = isHtml(content) ? content.value : escapeHtml(content);
    return template.content;
}

/**
 * Substitui o conteudo de `root` e devolve os elementos marcados com
 * `data-ref`, para dispensar uma enxurrada de `querySelector`.
 *
 *     const refs = render(root, html`<button data-ref="save">Salvar</button>`);
 *     refs.save.onclick = ...;
 */
export function render(root, content) {
    root.replaceChildren(toFragment(content));
    return refs(root);
}

/** Mapa `data-ref` -> elemento, dentro de `root`. */
export function refs(root) {
    const found = {};
    for (const element of root.querySelectorAll('[data-ref]')) {
        found[element.dataset.ref] = element;
    }
    return found;
}

let sequence = 0;
/** Id unico e estavel dentro da sessao, para `aria-describedby` e labels. */
export function uid(prefix = 'ui') {
    sequence += 1;
    return `${prefix}-${sequence}`;
}

/* --------------------------------------------------------------------- */
/* Formatacao                                                             */
/* --------------------------------------------------------------------- */

export function formatBytes(value) {
    const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
    let index = 0;
    let number = Number(value || 0);
    while (number >= 1024 && index < units.length - 1) {
        number /= 1024;
        index += 1;
    }
    return `${number.toFixed(index ? 2 : 0)} ${units[index]}`;
}

export function formatPercent(fraction) {
    return `${Math.round(Number(fraction || 0) * 100)}%`;
}

/* --------------------------------------------------------------------- */
/* Componentes                                                            */
/* --------------------------------------------------------------------- */

/** Tons validos de badge.  `partial`/`cached`/`exported`/`empty` sao estados
 *  de cache; os demais sao mensagem.  Vermelho (`danger`) so para erro. */
export const TONES = ['neutral', 'empty', 'partial', 'cached', 'exported', 'accent', 'success', 'warning', 'danger'];

/**
 * Pilula de estado.  `technical` guarda o valor cru do backend no `title`,
 * para que ele continue acessivel sem virar o texto principal.
 */
export function badge({ label, tone = 'neutral', technical = null }) {
    const title = technical ? html` title="${technical}"` : raw('');
    return html`<span class="ui-badge ui-badge--${TONES.includes(tone) ? tone : 'neutral'}"${title}>${label}</span>`;
}

/** Barra de progresso com rotulo acessivel. */
export function progressBar({ value = 0, max = 1, label = '', tone = 'accent' }) {
    const total = Number(max) || 1;
    const ratio = Math.max(0, Math.min(1, Number(value) / total));
    const percent = Math.round(ratio * 100);
    return html`<div class="ui-progress ui-progress--${tone}" role="progressbar"
        aria-valuenow="${percent}" aria-valuemin="0" aria-valuemax="100"
        aria-label="${label || 'Progresso'}"><span style="width:${percent}%"></span></div>`;
}

/**
 * Botao.  `reason` explica por que esta desabilitado -- um botao morto sem
 * explicacao e um dos defeitos que este redesign existe para corrigir.
 */
export function button({ label, ref = null, variant = 'secondary', disabled = false, reason = null, type = 'button' }) {
    const reasonId = disabled && reason ? uid('motivo') : null;
    const parts = [
        html`class="ui-btn ui-btn--${variant}"`,
        html` type="${type}"`,
        ref ? html` data-ref="${ref}"` : raw(''),
        disabled ? raw(' disabled') : raw(''),
        reasonId ? html` aria-describedby="${reasonId}" title="${reason}"` : raw(''),
    ];
    const hint = reasonId ? html`<span id="${reasonId}" class="ui-btn-reason">${reason}</span>` : raw('');
    return html`<span class="ui-btn-wrap"><button ${raw(parts.map(String).join(''))}>${label}</button>${hint}</span>`;
}

/** Campo de formulario com rotulo, dica e erro inline. */
export function field({ label, control, hint = null, error = null }) {
    return html`<label class="ui-field">
        <span class="ui-field-label">${label}</span>
        ${control}
        ${hint ? html`<span class="ui-field-hint">${hint}</span>` : raw('')}
        ${error ? html`<span class="ui-field-error" role="alert">${error}</span>` : raw('')}
    </label>`;
}

/** Agrupamento com titulo -- o que faltava por completo na UI dos plugins. */
export function section({ title, description = null, body, actions = null, ref = null }) {
    return html`<section class="ui-section"${ref ? html` data-ref="${ref}"` : raw('')}>
        <header class="ui-section-head">
            <h3 class="ui-section-title">${title}</h3>
            ${actions ? html`<div class="ui-section-actions">${actions}</div>` : raw('')}
        </header>
        ${description ? html`<p class="ui-section-description">${description}</p>` : raw('')}
        <div class="ui-section-body">${body}</div>
    </section>`;
}

export function emptyState(message) {
    return html`<p class="ui-empty">${message}</p>`;
}

export function spinner(label = 'Carregando') {
    return html`<span class="ui-spinner" role="status" aria-label="${label}"></span>`;
}

/** Linha de resultado ancorada a secao que a produziu (feedback no local). */
export function resultLine({ message, tone = 'neutral', ref = null }) {
    return html`<p class="ui-result ui-result--${tone}" role="status"${ref ? html` data-ref="${ref}"` : raw('')}>${message}</p>`;
}

/* --------------------------------------------------------------------- */
/* Estado de controles                                                    */
/* --------------------------------------------------------------------- */

/**
 * Marca um botao como ocupado: desabilita e mostra progresso, impedindo o
 * clique repetido que hoje nao tem nenhuma barreira.
 */
export function setBusy(element, busy, busyLabel = null) {
    if (!element) return;
    if (busy) {
        if (element.dataset.idleLabel == null) element.dataset.idleLabel = element.textContent;
        element.disabled = true;
        element.classList.add('is-busy');
        element.setAttribute('aria-busy', 'true');
        if (busyLabel) element.textContent = busyLabel;
    } else {
        element.disabled = false;
        element.classList.remove('is-busy');
        element.removeAttribute('aria-busy');
        if (element.dataset.idleLabel != null) {
            element.textContent = element.dataset.idleLabel;
            delete element.dataset.idleLabel;
        }
    }
}

/** Envolve uma acao assincrona no estado ocupado do botao que a disparou. */
export async function withBusy(element, busyLabel, action) {
    setBusy(element, true, busyLabel);
    try {
        return await action();
    } finally {
        setBusy(element, false);
    }
}

/**
 * Confirmacao destrutiva dentro do proprio painel, com resumo do impacto.
 * Substitui `confirm()` nativo, que aparece fora do contexto e nao consegue
 * mostrar o que sera perdido.
 *
 * Resolve `true` ao confirmar e `false` ao cancelar ou desmontar.
 */
export function inlineConfirm(container, { title, body, confirmLabel = 'Confirmar', cancelLabel = 'Cancelar', danger = true }) {
    return new Promise(resolve => {
        const view = render(container, html`<div class="ui-confirm${danger ? ' ui-confirm--danger' : ''}" role="alertdialog" aria-label="${title}">
            <p class="ui-confirm-title">${title}</p>
            <p class="ui-confirm-body">${body}</p>
            <div class="ui-confirm-actions">
                ${button({ label: cancelLabel, ref: 'cancel', variant: 'ghost' })}
                ${button({ label: confirmLabel, ref: 'confirm', variant: danger ? 'danger' : 'primary' })}
            </div>
        </div>`);
        const finish = answer => {
            container.replaceChildren();
            resolve(answer);
        };
        view.cancel.onclick = () => finish(false);
        view.confirm.onclick = () => finish(true);
        view.confirm.focus();
    });
}
