import { inlineConfirm } from './modules/ui.js';

const socket = io();

const sourceSelect = document.getElementById('source-select');
const folders = document.getElementById('folder-grid');
const videos = document.getElementById('video-grid');
const breadcrumbs = document.getElementById('breadcrumbs-container');
const breadcrumbsNav = document.getElementById('breadcrumbs-nav');
const statusMessage = document.getElementById('status-message');
const searchForm = document.getElementById('catalog-search');
const searchInput = document.getElementById('catalog-search-input');
const sourceToolsButton = document.getElementById('source-tools-button');
const toolsModal = document.getElementById('tools-modal');
const toolsRoot = document.getElementById('tools-modal-body');
const inspectorModal = document.getElementById('inspector-modal');
const inspectorRoot = document.getElementById('inspector-plugin-root');
const inspectorFavorite = document.getElementById('inspector-favorite');
const rtcModeSelect = document.getElementById('rtc-mode-select');
const rtcModeDescription = document.getElementById('rtc-mode-description');
const rtcModeStatus = document.getElementById('rtc-mode-status');
const remoteAdminToggle = document.getElementById('remote-host-admin-toggle');
const remoteAdminStatus = document.getElementById('remote-host-admin-status');
const sourceDiagnostics = document.getElementById('source-diagnostics');
const catalogPagination = document.getElementById('catalog-pagination');
const toolsTitle = document.getElementById('tools-modal-title');
const toolsContext = document.getElementById('tools-modal-context');
const inspectorTitle = document.getElementById('inspector-modal-title');
const inspectorContext = document.getElementById('inspector-modal-context');
const videoSectionTitle = document.getElementById('video-section-title');
const folderSection = document.getElementById('folder-section');
const folderSectionTitle = document.getElementById('folder-section-title');

let sourceId = null;
let sources = new Map();
let trail = [];
let activeView = 'popular';
let sourceExtension = null;
let toolsExtension = null;
let inspectorExtension = null;
let inspectedItem = null;
let statusTimeout;
let pageIndex = 0;
let pageCursors = [null];
let nextCursor = null;
let paginationLoader = null;
// Ultimo catalogo renderizado.  Serve a duas coisas: notifyChanged() decide
// se vale recarregar (um job que terminou fora da tela nao mexe nela), e um
// modal aberto depois da renderizacao recebe o estado atual na montagem.
let renderedItems = [];
let renderedParentId = null;
let renderedIds = new Set();
// Refaz exatamente a consulta que produziu a tela atual (catalogo ou busca,
// na mesma pasta e na mesma pagina).  Mesmo formato de paginationLoader.
let reloadCurrent = () => loadCatalog();

const nativeViews = [
    ['popular', 'Popular'], ['new', 'Novidades'], ['az', 'A-Z'],
    ['genres', 'Gêneros'], ['history', 'Histórico'], ['favorites', 'Favoritos']
];

// Aviso global.  Reservado ao que acontece fora da tela visivel; feedback de
// uma acao pertence ao controle que a disparou.
function showStatus(message, type = 'success') {
    clearTimeout(statusTimeout);
    statusMessage.textContent = message;
    statusMessage.className = `host-status host-status--${type === 'error' ? 'error' : 'success'}`;
    statusMessage.hidden = false;
    statusTimeout = setTimeout(() => { statusMessage.hidden = true; }, 4000);
}

function imageUrl(item) {
    return (item.entry_type === 'collection' ? item.poster?.url : item.thumbnail?.url)
        || item.image?.url || (item.entry_type === 'collection' ? '/banner_folder.png' : '/banner_video.png');
}

function entityKind(item) {
    return item.entity_kind || item.id?.split(':', 1)[0]
        || (item.entry_type === 'playable' ? 'video' : 'collection');
}

function sourceRequest(key, action, options = {}) {
    return fetch(`/host/${encodeURIComponent(key)}/${action.replace(/^\/+/, '')}`, options)
        .then(async response => {
            const type = response.headers.get('content-type') || '';
            const body = type.includes('json') ? await response.json() : await response.text();
            if (!response.ok) throw new Error(body?.detail || body || 'Ação da origem falhou.');
            return body;
        });
}

function fallbackAction(item) {
    return item.entry_type === 'collection' ? navigate(item.id, item.title) : selectMedia(item.id);
}

function snapshot(item) {
    return { image: item.image, poster: item.poster, thumbnail: item.thumbnail };
}

async function toggleFavorite(item, input = null) {
    const kind = entityKind(item);
    const previous = item.favorited;
    item.favorited = !previous;
    if (input) input.checked = item.favorited;
    try {
        const response = await fetch('/api/favorites', {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source_id: sourceId, media_id: item.id, entity_kind: kind,
                title: item.title, snapshot: snapshot(item), favorite: item.favorited })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail);
        item.favorited = data.favorited;
        if (input) input.checked = item.favorited;
        showStatus(item.favorited ? 'Adicionado aos favoritos.' : 'Removido dos favoritos.');
        if (activeView === 'favorites') await loadCatalog();
    } catch (error) {
        item.favorited = previous;
        if (input) input.checked = previous;
        showStatus(error.message || 'Não foi possível alterar o favorito.', 'error');
    }
}

function card(item) {
    // entry_type === 'collection' ? 'folder' : 'video'
    const visualType = item.entry_type === 'collection' ? 'folder' : 'video';
    const element = document.createElement('article');
    element.className = `media-item ${visualType}`;
    element.title = item.title;

    const body = document.createElement('button');
    body.type = 'button';
    body.className = 'media-card-body';
    body.onclick = () => sourceExtension?.bodyAction
        ? sourceExtension.bodyAction(item, { navigate, selectMedia, openInspector, showStatus })
        : fallbackAction(item);

    const image = document.createElement('img');
    image.className = 'banner';
    image.alt = '';
    image.loading = 'lazy';
    image.src = imageUrl(item);
    image.onerror = () => {
        image.onerror = null;
        image.src = item.entry_type === 'collection' ? '/banner_folder.png' : '/banner_video.png';
    };
    const indicator = document.createElement('span');
    indicator.className = 'type-indicator';
    indicator.textContent = entityKind(item);
    body.append(indicator, image);

    if (item.history || item.cache) {
        const progress = document.createElement('div');
        progress.className = 'media-progress';
        const value = item.history?.duration ? item.history.position / item.history.duration
            : item.cache?.coverage || 0;
        const fill = document.createElement('span');
        fill.style.width = `${Math.max(0, Math.min(1, Number(value) || 0)) * 100}%`;
        progress.appendChild(fill);
        body.appendChild(progress);
    }

    const title = document.createElement('button');
    title.type = 'button';
    title.className = 'file-name';
    title.textContent = item.title;
    title.onclick = () => sourceExtension?.titleAction
        ? sourceExtension.titleAction(item, { openInspector, navigate, selectMedia, showStatus })
        : (sourceExtension?.module?.mountInspector ? openInspector(item) : fallbackAction(item));

    const favorite = document.createElement('button');
    favorite.type = 'button';
    favorite.className = `favorite-badge ${item.favorited ? 'is-favorite' : ''}`;
    favorite.textContent = item.favorited ? '★' : '☆';
    favorite.setAttribute('aria-label', item.favorited ? 'Desfavoritar' : 'Favoritar');
    favorite.onclick = event => {
        event.stopPropagation();
        toggleFavorite(item).then(() => {
            favorite.textContent = item.favorited ? '★' : '☆';
            favorite.classList.toggle('is-favorite', item.favorited);
            favorite.setAttribute('aria-label', item.favorited ? 'Desfavoritar' : 'Favoritar');
        });
    };

    element.append(body, title, favorite);
    sourceExtension?.decorateCard?.(item, element);
    return element;
}

function resetPagination() {
    pageIndex = 0;
    pageCursors = [null];
    nextCursor = null;
}

function renderPagination(cursor) {
    nextCursor = cursor || null;
    catalogPagination.replaceChildren();
    const hasPrevious = pageIndex > 0;
    if (!hasPrevious && !nextCursor) {
        catalogPagination.hidden = true;
        return;
    }
    catalogPagination.hidden = false;
    const previous = document.createElement('button');
    previous.type = 'button';
    previous.className = 'ui-btn ui-btn--secondary';
    previous.textContent = 'Anterior';
    previous.disabled = !hasPrevious;
    previous.onclick = () => {
        if (!hasPrevious || !paginationLoader) return;
        pageIndex -= 1;
        paginationLoader(pageCursors[pageIndex]);
    };
    const indicator = document.createElement('span');
    indicator.className = 'catalog-page-indicator';
    indicator.textContent = `Página ${pageIndex + 1}`;
    const next = document.createElement('button');
    next.type = 'button';
    next.className = 'ui-btn ui-btn--secondary';
    next.textContent = 'Próxima';
    next.disabled = !nextCursor;
    next.onclick = () => {
        if (!nextCursor || !paginationLoader) return;
        pageCursors[pageIndex + 1] = nextCursor;
        pageIndex += 1;
        paginationLoader(nextCursor);
    };
    catalogPagination.append(previous, indicator, next);
}

function renderViews() {
    const root = document.getElementById('catalog-views');
    root.replaceChildren();
    let actions = document.getElementById('catalog-view-actions');
    if (!actions) {
        actions = document.createElement('div');
        actions.id = 'catalog-view-actions';
        actions.className = 'catalog-view-actions';
        searchForm.before(actions);
    }
    actions.replaceChildren();
    if (activeView === 'history') {
        const clear = document.createElement('button');
        clear.type = 'button';
        clear.className = 'ui-btn ui-btn--ghost';
        clear.textContent = 'Limpar histórico';
        clear.onclick = async () => {
            await fetch(`/api/history?source_id=${encodeURIComponent(sourceId)}`, { method: 'DELETE' });
            await loadCatalog();
        };
        actions.appendChild(clear);
    }
    const pluginViews = (sources.get(sourceId)?.views || []).map(view => [view.id, view.label, true]);
    [...nativeViews, ...pluginViews].forEach(([id, label], index) => {
        if (index === nativeViews.length && pluginViews.length) {
            const separator = document.createElement('div');
            separator.className = 'catalog-views-separator';
            root.appendChild(separator);
        }
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `catalog-view ${id === activeView ? 'active' : ''}`;
        button.textContent = label;
        button.dataset.view = id;
        button.onclick = () => changeView(id);
        root.appendChild(button);
    });
}

function renderBreadcrumbs() {
    breadcrumbs.replaceChildren();
    const visible = trail.length > 0;
    breadcrumbsNav.hidden = !visible;
    if (!visible) return;
    [{ id: null, title: 'Início' }, ...trail].forEach((entry, index) => {
        if (index) {
            const separator = document.createElement('li');
            separator.textContent = '›';
            breadcrumbs.appendChild(separator);
        }
        const li = document.createElement('li');
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'catalog-crumb';
        button.textContent = entry.title;
        button.onclick = () => {
            trail = trail.slice(0, index);
            loadCatalog(entry.id, false, null, null);
        };
        li.appendChild(button);
        breadcrumbs.appendChild(li);
    });
}

function emptyMessage(view, kind) {
    if (view === 'history') return 'Nada assistido ainda.';
    if (view === 'favorites') return 'Nenhum favorito nesta origem.';
    if (view === 'cache-local') return 'Nada em cache localmente.';
    return kind === 'folder' ? 'Nenhuma coleção.' : 'Nenhum vídeo.';
}

function emptyNotice(message) {
    const value = document.createElement('p');
    value.className = 'catalog-empty';
    value.textContent = message;
    return value;
}

function renderItems(items, parentId = null) {
    folders.replaceChildren();
    videos.replaceChildren();
    renderedItems = items;
    renderedParentId = parentId;
    renderedIds = new Set(items.map(item => item.id));
    const collections = items.filter(item => item.entry_type === 'collection');
    const playable = items.filter(item => item.entry_type === 'playable');
    const historyRoot = activeView === 'history' && trail.length === 0;
    const favoritesRoot = activeView === 'favorites' && trail.length === 0;
    videoSectionTitle.textContent = historyRoot ? 'Histórico' : (favoritesRoot ? 'Episódios e filmes' : 'Vídeos');
    folderSectionTitle.textContent = favoritesRoot ? 'Séries e temporadas' : 'Pastas';
    folderSection.hidden = historyRoot;

    if (historyRoot) {
        [...collections, ...playable].forEach(item => videos.appendChild(card(item)));
    } else {
        collections.forEach(item => folders.appendChild(card(item)));
        playable.forEach(item => {
            const value = card(item);
            if (activeView === 'history') {
                const remove = document.createElement('button');
                remove.type = 'button';
                remove.className = 'media-card-remove';
                remove.textContent = 'Remover do histórico';
                remove.onclick = async () => {
                    await fetch(`/api/history/${encodeURIComponent(sourceId)}/${encodeURIComponent(item.id)}?entity_kind=${encodeURIComponent(entityKind(item))}`, { method: 'DELETE' });
                    await loadCatalog();
                };
                value.appendChild(remove);
            }
            videos.appendChild(value);
        });
    }
    const historyItems = historyRoot ? [...collections, ...playable] : null;
    if (!collections.length && !historyRoot) folders.appendChild(emptyNotice(emptyMessage(activeView, 'folder')));
    if (!(historyRoot ? historyItems.length : playable.length)) videos.appendChild(emptyNotice(emptyMessage(activeView, 'video')));
}

async function loadCatalog(parentId = null, push = false, title = null, cursor = null, keepPagination = false) {
    if (!sourceId) return;
    if (push && parentId !== null) {
        trail.push({ id: parentId, title });
    }
    if (!keepPagination) resetPagination();
    paginationLoader = next => loadCatalog(parentId, false, null, next, true);
    reloadCurrent = () => loadCatalog(parentId, false, null, cursor, true);
    renderBreadcrumbs();
    document.getElementById('catalog-loading').hidden = false;
    folders.replaceChildren();
    videos.replaceChildren();
    const params = new URLSearchParams({ source_id: sourceId, view: activeView });
    if (parentId !== null) params.set('parent_id', parentId);
    if (cursor !== null) params.set('cursor', cursor);
    try {
        const response = await fetch(`/api/catalog?${params}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail);
        renderItems(data.items, parentId);
        renderPagination(data.next_cursor);
        notifyCatalogRendered({ items: data.items, parentId });
    } catch (error) {
        showStatus(error.message || 'Origem indisponível.', 'error');
        renderPagination(null);
    } finally {
        document.getElementById('catalog-loading').hidden = true;
    }
}

async function runSearch(query, cursor = null, keepPagination = false) {
    if (!keepPagination) resetPagination();
    paginationLoader = next => runSearch(query, next, true);
    reloadCurrent = () => runSearch(query, cursor, true);
    renderBreadcrumbs();
    document.getElementById('catalog-loading').hidden = false;
    try {
        const params = new URLSearchParams({ source_id: sourceId, q: query });
        if (cursor !== null) params.set('cursor', cursor);
        const response = await fetch(`/api/search?${params}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail);
        renderItems(data.items, null);
        renderPagination(data.next_cursor);
        notifyCatalogRendered({ items: data.items, parentId: null });
    } catch (error) {
        showStatus(error.message || 'Busca indisponível.', 'error');
        renderPagination(null);
    } finally {
        document.getElementById('catalog-loading').hidden = true;
    }
}

function navigate(id, title) {
    return loadCatalog(id, true, title);
}

function selectMedia(mediaId) {
    socket.emit('host_set_video', { source_id: sourceId, media_id: mediaId });
    showStatus('Mídia selecionada.');
}

async function changeView(view) {
    activeView = view;
    trail = [];
    searchInput.value = '';
    await loadCatalog();
    renderViews();
}

/* --- Contrato do plugin ---------------------------------------------- */

/**
 * Entrega `catalogRendered` a TODOS os niveis que podem implementa-lo.
 *
 * Ate aqui o host so chamava `sourceExtension.catalogRendered`, ou seja, o
 * export de modulo -- mas os dois plugins devolvem o hook de `mount()`, que
 * e onde o estado vive.  Resultado: o hook nunca disparava e a lista de
 * midias das Ferramentas ficava presa no que existia quando o modal abriu.
 */
function notifyCatalogRendered(state) {
    for (const target of [sourceExtension, toolsExtension, inspectorExtension]) {
        try { target?.catalogRendered?.(state); } catch (error) { console.warn(error); }
    }
}

/**
 * Recarrega a tela quando algo que ela mostra mudou -- tipicamente um job
 * que terminou.  Sem isso o job acaba e os cards seguem exibindo o estado
 * anterior ate alguem navegar.
 *
 * `entityIds` omitido significa "nao sei quais"; com ids, o host so paga o
 * recarregamento se algum deles estiver realmente visivel.  Devolve se
 * recarregou, para o plugin nao precisar adivinhar.
 */
async function notifyChanged(entityIds = null) {
    const ids = entityIds == null ? null : [entityIds].flat().filter(Boolean);
    if (ids && !ids.some(id => renderedIds.has(id))) return false;
    await reloadCurrent();
    return true;
}

/**
 * Deixa o plugin nomear o cabecalho do modal.  O host so sabe o valor cru do
 * backend (`series`, `episode`), entao sem isto o Inspetor exibe
 * "series · Crunchyroll" -- e o plugin, que sabe traduzir, nao alcanca o
 * elemento.  Passar so `title` ou so `subtitle` mantem o outro.
 */
function headerSetter(titleElement, subtitleElement) {
    return ({ title = null, subtitle = null } = {}) => {
        if (title != null) titleElement.textContent = title;
        if (subtitle != null && subtitleElement) subtitleElement.textContent = subtitle;
    };
}

/**
 * Confirmacao destrutiva dentro do proprio modal, no lugar do `confirm()`
 * nativo -- que aparece fora do contexto, nao mostra o que sera perdido e
 * nao da para estilizar.  Resolve `false` se o modal fechar antes.
 */
const pendingConfirms = new Map();

function confirmIn(modal) {
    return options => new Promise(resolve => {
        const slot = document.createElement('div');
        slot.className = 'host-confirm-slot';
        modal.querySelector('.host-modal-panel').appendChild(slot);
        const waiting = pendingConfirms.get(modal) || new Set();
        pendingConfirms.set(modal, waiting);
        let settled = false;
        const finish = answer => {
            if (settled) return;
            settled = true;
            waiting.delete(finish);
            slot.remove();
            resolve(answer);
        };
        waiting.add(finish);
        inlineConfirm(slot, options).then(finish);
    });
}

/** Fechar o modal e responder "nao" -- nunca deixar o plugin esperando. */
function cancelConfirms(modal) {
    for (const finish of pendingConfirms.get(modal) || []) finish(false);
    pendingConfirms.delete(modal);
}

/** Parte do contexto que Ferramentas e Inspetor recebem igual. */
function sharedContext() {
    return {
        source: sources.get(sourceId),
        request: (action, options) => sourceRequest(sourceId, action, options),
        showStatus,
        notifyChanged,
    };
}

async function closeTools() {
    cancelConfirms(toolsModal);
    try { await toolsExtension?.cleanup?.(); } catch (error) { console.warn(error); }
    toolsExtension = null;
    toolsRoot.replaceChildren();
    toolsModal.hidden = true;
}

async function closeInspector() {
    cancelConfirms(inspectorModal);
    try { await inspectorExtension?.cleanup?.(); } catch (error) { console.warn(error); }
    inspectorExtension = null;
    inspectorRoot.replaceChildren();
    inspectorModal.hidden = true;
    inspectedItem = null;
}

async function loadSourceExtension(source) {
    await closeTools();
    await closeInspector();
    sourceExtension = null;
    sourceToolsButton.hidden = true;
    if (!source?.host_module) return;
    try {
        const module = await import(`${source.host_module}?v=${encodeURIComponent(source.type || '')}`);
        sourceExtension = { module, ...module };
        sourceToolsButton.hidden = !(source.host_capabilities || []).includes('tools');
        renderViews();
    } catch (error) {
        showStatus('Não foi possível carregar a extensão desta origem.', 'error');
    }
}

async function openTools() {
    if (!sourceExtension?.module?.mount) return;
    toolsModal.hidden = false;
    toolsTitle.textContent = 'Ferramentas';
    toolsContext.textContent = sources.get(sourceId)?.label || sourceId;
    toolsRoot.textContent = 'Carregando...';
    try {
        const mounted = await sourceExtension.module.mount({ ...sharedContext(), root: toolsRoot,
            navigate, refresh: () => loadCatalog(trail.at(-1)?.id || null, false), openInspector,
            setHeader: headerSetter(toolsTitle, toolsContext), confirm: confirmIn(toolsModal) });
        toolsExtension = typeof mounted === 'function' ? { cleanup: mounted } : (mounted || {});
        // O modal pode ter aberto sobre um catalogo ja renderizado: entrega o
        // estado atual em vez de esperar a proxima navegacao.
        if (renderedIds.size) toolsExtension.catalogRendered?.({ items: renderedItems, parentId: renderedParentId });
    } catch (error) {
        toolsRoot.textContent = error.message || 'Extensão indisponível.';
        showStatus('Não foi possível montar as ferramentas.', 'error');
    }
}

async function openInspector(item) {
    if (!sourceExtension?.module?.mountInspector) return fallbackAction(item);
    inspectedItem = item;
    // Valor cru do backend como texto de interface e o que setHeader existe
    // para corrigir: fica so ate o plugin dizer como se chama de verdade.
    inspectorTitle.textContent = item.title;
    inspectorContext.textContent = `${entityKind(item)} · ${sources.get(sourceId)?.label || sourceId}`;
    inspectorFavorite.checked = !!item.favorited;
    inspectorRoot.textContent = 'Carregando...';
    inspectorModal.hidden = false;
    try {
        const mounted = await sourceExtension.module.mountInspector({ ...sharedContext(), entity: item,
            root: inspectorRoot, selectMedia, openTools,
            setHeader: headerSetter(inspectorTitle, inspectorContext), confirm: confirmIn(inspectorModal) });
        inspectorExtension = typeof mounted === 'function' ? { cleanup: mounted } : (mounted || {});
    } catch (error) {
        inspectorRoot.textContent = error.message || 'Inspetor indisponível.';
        showStatus('Não foi possível montar o inspetor.', 'error');
    }
}

sourceToolsButton.onclick = openTools;
inspectorFavorite.onchange = () => inspectedItem && toggleFavorite(inspectedItem, inspectorFavorite);
document.querySelectorAll('[data-close-modal]').forEach(button => {
    button.onclick = () => button.dataset.closeModal === 'tools-modal' ? closeTools() : closeInspector();
});
[toolsModal, inspectorModal].forEach(modal => {
    modal.onclick = event => { if (event.target === modal) (modal === toolsModal ? closeTools() : closeInspector()); };
});
document.addEventListener('keydown', event => {
    if (event.key === 'Escape') { closeTools(); closeInspector(); }
});

searchForm.onsubmit = async event => {
    event.preventDefault();
    const query = searchInput.value.trim();
    if (query && sourceId) await runSearch(query);
};

sourceSelect.onchange = async () => {
    sourceId = sourceSelect.value;
    activeView = 'popular';
    trail = [];
    await loadSourceExtension(sources.get(sourceId));
    renderViews();
    await loadCatalog();
};

socket.on('media_selection_error', data => showStatus(data.message, 'error'));

async function loadSources() {
    try {
        const response = await fetch('/api/sources');
        const data = await response.json();
        if (!response.ok) throw new Error();
        sources = new Map(data.sources.map(source => [source.id, source]));
        sourceSelect.replaceChildren();
        sourceDiagnostics.replaceChildren();
        (data.diagnostics || []).forEach(diagnostic => {
            const li = document.createElement('li');
            li.textContent = `${diagnostic.plugin}: ${diagnostic.message}`;
            sourceDiagnostics.appendChild(li);
        });
        data.sources.forEach(source => {
            const option = document.createElement('option');
            option.value = source.id;
            option.textContent = source.label;
            sourceSelect.appendChild(option);
        });
        sourceId = data.sources[0]?.id || null;
        renderViews();
        if (sourceId) {
            await loadSourceExtension(sources.get(sourceId));
            await loadCatalog();
        } else showStatus('Nenhuma origem de mídia disponível.', 'error');
    } catch (error) {
        showStatus('Não foi possível carregar as origens.', 'error');
    }
}

fetch('/api/get_ip').then(response => response.json())
    .then(data => document.getElementById('invite-link-field').value = data.link);
document.getElementById('copy-link-btn').onclick = async () => {
    await navigator.clipboard.writeText(document.getElementById('invite-link-field').value);
    showStatus('Link copiado.');
};

const rtcDescriptions = { off: 'Usa somente STUN.', auto: 'Usa TURN como fallback.', relay: 'Todo o tráfego WebRTC passa pelo TURN.' };
async function loadRtc() {
    const response = await fetch('/api/rtc_mode');
    const data = await response.json();
    rtcModeSelect.value = data.mode;
    rtcModeDescription.textContent = rtcDescriptions[data.mode];
    for (const option of rtcModeSelect.options) option.disabled = !data.turnConfigured && option.value !== 'off';
}
rtcModeSelect.onchange = async () => {
    const mode = rtcModeSelect.value;
    const response = await fetch('/api/rtc_mode', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode }) });
    const data = await response.json();
    if (response.ok) { rtcModeDescription.textContent = rtcDescriptions[mode]; rtcModeStatus.textContent = 'Modo salvo.'; }
    else rtcModeStatus.textContent = data.detail || 'Não foi possível salvar.';
};

async function loadRemoteAdmin() {
    const response = await fetch('/api/host/remote-access');
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail);
    remoteAdminToggle.checked = data.enabled;
    remoteAdminToggle.disabled = !data.canChange;
    remoteAdminStatus.textContent = data.enabled ? 'Qualquer cliente da rede pode administrar este servidor.' : 'O painel está restrito ao localhost.';
}
remoteAdminToggle.onchange = async () => {
    const enabled = remoteAdminToggle.checked;
    const response = await fetch('/api/host/remote-access', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) });
    const data = await response.json();
    if (!response.ok) { remoteAdminToggle.checked = !enabled; showStatus(data.detail, 'error'); return; }
    remoteAdminStatus.textContent = data.enabled ? 'Administração remota habilitada sem autenticação.' : 'O painel está restrito ao localhost.';
};

loadSources();
loadRtc();
loadRemoteAdmin().catch(error => showStatus(error.message, 'error'));
