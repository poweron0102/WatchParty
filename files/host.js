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
let modalReturnFocus = null;

const nativeViews = [
    ['popular', 'Popular'], ['new', 'Novidades'], ['az', 'A-Z'],
    ['genres', 'Gêneros'], ['history', 'Histórico'], ['favorites', 'Favoritos']
];

function showStatus(message, type = 'success') {
    clearTimeout(statusTimeout);
    statusMessage.textContent = message;
    statusMessage.className = `mb-6 rounded-md px-4 py-3 ${type === 'error' ? 'bg-red-900/50' : 'bg-green-900/50'}`;
    statusTimeout = setTimeout(() => statusMessage.classList.add('hidden'), 4000);
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
    if (input) {
        if ('checked' in input) input.checked = item.favorited;
        input.setAttribute('aria-pressed', String(item.favorited));
        input.setAttribute('aria-label', item.favorited ? 'Desfavoritar' : 'Favoritar');
        if (input.classList.contains('inspector-favorite')) input.firstChild.textContent = item.favorited ? '★ ' : '☆ ';
    }
    try {
        const response = await fetch('/api/favorites', {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source_id: sourceId, media_id: item.id, entity_kind: kind,
                title: item.title, snapshot: snapshot(item), favorite: item.favorited })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail);
        item.favorited = data.favorited;
        if (input) {
            if ('checked' in input) input.checked = item.favorited;
            input.setAttribute('aria-pressed', String(item.favorited));
            input.setAttribute('aria-label', item.favorited ? 'Desfavoritar' : 'Favoritar');
            if (input.classList.contains('inspector-favorite')) input.firstChild.textContent = item.favorited ? '★ ' : '☆ ';
        }
        showStatus(item.favorited ? 'Adicionado aos favoritos.' : 'Removido dos favoritos.');
        if (activeView === 'favorites') await loadCatalog();
    } catch (error) {
        item.favorited = previous;
        if (input) {
            if ('checked' in input) input.checked = previous;
            input.setAttribute('aria-pressed', String(previous));
            input.setAttribute('aria-label', previous ? 'Desfavoritar' : 'Favoritar');
            if (input.classList.contains('inspector-favorite')) input.firstChild.textContent = previous ? '★ ' : '☆ ';
        }
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
    body.className = 'block w-full text-left';
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
        catalogPagination.classList.add('hidden');
        return;
    }
    catalogPagination.classList.remove('hidden');
    const previous = document.createElement('button');
    previous.type = 'button';
    previous.className = 'bg-input px-3 py-2 rounded-md';
    previous.textContent = 'Anterior';
    previous.disabled = !hasPrevious;
    previous.onclick = () => {
        if (!hasPrevious || !paginationLoader) return;
        pageIndex -= 1;
        paginationLoader(pageCursors[pageIndex]);
    };
    const indicator = document.createElement('span');
    indicator.className = 'text-sm text-gray-400';
    indicator.textContent = `Página ${pageIndex + 1}`;
    const next = document.createElement('button');
    next.type = 'button';
    next.className = 'bg-input px-3 py-2 rounded-md';
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
        actions.className = 'flex justify-end gap-2 mb-2';
        searchForm.before(actions);
    }
    actions.replaceChildren();
    if (activeView === 'history') {
        const clear = document.createElement('button');
        clear.type = 'button';
        clear.className = 'text-sm brand hover:underline';
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
            separator.className = 'border-t border-input my-2';
            root.appendChild(separator);
        }
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `view-item text-left px-3 py-2 rounded-md ${id === activeView ? 'active' : ''}`;
        button.textContent = label;
        button.dataset.view = id;
        button.onclick = () => changeView(id);
        root.appendChild(button);
    });
}

function renderBreadcrumbs() {
    breadcrumbs.replaceChildren();
    const visible = trail.length > 0;
    breadcrumbsNav.classList.toggle('hidden', !visible);
    if (!visible) return;
    [{ id: null, title: 'Início' }, ...trail].forEach((entry, index) => {
        if (index) {
            const separator = document.createElement('li');
            separator.textContent = '›';
            breadcrumbs.appendChild(separator);
        }
        const li = document.createElement('li');
        const button = document.createElement('button');
        button.className = 'brand hover:underline';
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

function renderItems(items) {
    folders.replaceChildren();
    videos.replaceChildren();
    const collections = items.filter(item => item.entry_type === 'collection');
    const playable = items.filter(item => item.entry_type === 'playable');
    const historyRoot = activeView === 'history' && trail.length === 0;
    const favoritesRoot = activeView === 'favorites' && trail.length === 0;
    videoSectionTitle.textContent = historyRoot ? 'Histórico' : (favoritesRoot ? 'Episódios e filmes' : 'Vídeos');
    folderSectionTitle.textContent = favoritesRoot ? 'Séries e temporadas' : 'Pastas';
    folderSection.classList.toggle('hidden', historyRoot);

    if (historyRoot) {
        [...collections, ...playable].forEach(item => videos.appendChild(card(item)));
    } else {
        collections.forEach(item => folders.appendChild(card(item)));
        playable.forEach(item => {
            const value = card(item);
            if (activeView === 'history') {
                const remove = document.createElement('button');
                remove.type = 'button';
                remove.className = 'text-xs text-red-300 px-2 pb-2';
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
    if (!collections.length && !historyRoot) folders.innerHTML = `<p class="text-gray-500">${emptyMessage(activeView, 'folder')}</p>`;
    if (!(historyRoot ? historyItems.length : playable.length)) videos.innerHTML = `<p class="text-gray-500">${emptyMessage(activeView, 'video')}</p>`;
}

async function loadCatalog(parentId = null, push = false, title = null, cursor = null, keepPagination = false) {
    if (!sourceId) return;
    if (push && parentId !== null) {
        trail.push({ id: parentId, title });
    }
    if (!keepPagination) resetPagination();
    paginationLoader = next => loadCatalog(parentId, false, null, next, true);
    renderBreadcrumbs();
    document.getElementById('catalog-loading').classList.remove('hidden');
    folders.replaceChildren();
    videos.replaceChildren();
    const params = new URLSearchParams({ source_id: sourceId, view: activeView });
    if (parentId !== null) params.set('parent_id', parentId);
    if (cursor !== null) params.set('cursor', cursor);
    try {
        const response = await fetch(`/api/catalog?${params}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail);
        renderItems(data.items);
        renderPagination(data.next_cursor);
        sourceExtension?.catalogRendered?.({ items: data.items, parentId });
    } catch (error) {
        showStatus(error.message || 'Origem indisponível.', 'error');
        renderPagination(null);
    } finally {
        document.getElementById('catalog-loading').classList.add('hidden');
    }
}

async function runSearch(query, cursor = null, keepPagination = false) {
    if (!keepPagination) resetPagination();
    paginationLoader = next => runSearch(query, next, true);
    renderBreadcrumbs();
    document.getElementById('catalog-loading').classList.remove('hidden');
    try {
        const params = new URLSearchParams({ source_id: sourceId, q: query });
        if (cursor !== null) params.set('cursor', cursor);
        const response = await fetch(`/api/search?${params}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail);
        renderItems(data.items);
        renderPagination(data.next_cursor);
    } catch (error) {
        showStatus(error.message || 'Busca indisponível.', 'error');
        renderPagination(null);
    } finally {
        document.getElementById('catalog-loading').classList.add('hidden');
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

async function closeTools() {
    try { await toolsExtension?.cleanup?.(); } catch (error) { console.warn(error); }
    toolsExtension = null;
    toolsRoot.replaceChildren();
    toolsModal.classList.add('hidden');
    toolsModal.classList.remove('flex');
    if (modalReturnFocus?.isConnected) modalReturnFocus.focus();
    modalReturnFocus = null;
}

async function closeInspector() {
    try { await inspectorExtension?.cleanup?.(); } catch (error) { console.warn(error); }
    inspectorExtension = null;
    inspectorRoot.replaceChildren();
    inspectorModal.classList.add('hidden');
    inspectorModal.classList.remove('flex');
    inspectedItem = null;
    if (modalReturnFocus?.isConnected) modalReturnFocus.focus();
    modalReturnFocus = null;
}

async function loadSourceExtension(source) {
    await closeTools();
    await closeInspector();
    sourceExtension = null;
    sourceToolsButton.classList.add('hidden');
    if (!source?.host_module) return;
    try {
        const module = await import(`${source.host_module}?v=${encodeURIComponent(source.type || '')}`);
        sourceExtension = { module, ...module };
        sourceToolsButton.classList.toggle('hidden', !(source.host_capabilities || []).includes('tools'));
        renderViews();
    } catch (error) {
        showStatus('Não foi possível carregar a extensão desta origem.', 'error');
    }
}

async function openTools() {
    if (!sourceExtension?.module?.mount) return;
    modalReturnFocus = document.activeElement;
    toolsModal.classList.remove('hidden');
    toolsModal.classList.add('flex');
    document.getElementById('tools-modal-title').textContent = `Ferramentas — ${sources.get(sourceId)?.label || sourceId}`;
    toolsRoot.textContent = 'Carregando...';
    document.getElementById('tools-modal-title').focus();
    try {
        const mounted = await sourceExtension.module.mount({ source: sources.get(sourceId), root: toolsRoot,
            request: (action, options) => sourceRequest(sourceId, action, options),
            navigate, refresh: () => loadCatalog(trail.at(-1)?.id || null, false), showStatus, openInspector });
        toolsExtension = typeof mounted === 'function' ? { cleanup: mounted } : (mounted || {});
    } catch (error) {
        toolsRoot.textContent = error.message || 'Extensão indisponível.';
        showStatus('Não foi possível montar as ferramentas.', 'error');
    }
}

async function openInspector(item) {
    if (!sourceExtension?.module?.mountInspector) return fallbackAction(item);
    modalReturnFocus = document.activeElement;
    inspectedItem = item;
    document.getElementById('inspector-modal-title').textContent = item.title;
    document.getElementById('inspector-modal-context').textContent = `${entityKind(item)} · ${sources.get(sourceId)?.label || sourceId}`;
    inspectorFavorite.setAttribute('aria-pressed', String(!!item.favorited));
    inspectorFavorite.setAttribute('aria-label', item.favorited ? 'Desfavoritar' : 'Favoritar');
    inspectorFavorite.firstChild.textContent = item.favorited ? '★ ' : '☆ ';
    inspectorRoot.textContent = 'Carregando...';
    inspectorModal.classList.remove('hidden');
    inspectorModal.classList.add('flex');
    document.getElementById('inspector-modal-title').focus();
    try {
        const mounted = await sourceExtension.module.mountInspector({ source: sources.get(sourceId), entity: item,
            root: inspectorRoot, request: (action, options) => sourceRequest(sourceId, action, options),
            showStatus, selectMedia, openTools });
        inspectorExtension = typeof mounted === 'function' ? { cleanup: mounted } : (mounted || {});
    } catch (error) {
        inspectorRoot.textContent = error.message || 'Inspetor indisponível.';
        showStatus('Não foi possível montar o inspetor.', 'error');
    }
}

sourceToolsButton.onclick = openTools;
inspectorFavorite.onclick = () => inspectedItem && toggleFavorite(inspectedItem, inspectorFavorite);
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
