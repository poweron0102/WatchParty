const socket = io();
const sourceSelect = document.getElementById('source-select');
const folders = document.getElementById('folder-grid');
const videos = document.getElementById('video-grid');
const breadcrumbs = document.getElementById('breadcrumbs-container');
const statusMessage = document.getElementById('status-message');
const rtcModeSelect = document.getElementById('rtc-mode-select');
const rtcModeDescription = document.getElementById('rtc-mode-description');
const rtcModeStatus = document.getElementById('rtc-mode-status');
const searchForm = document.getElementById('catalog-search');
const searchInput = document.getElementById('catalog-search-input');
let sourceId = null;
let trail = [];
let statusTimeout;
let previousRtcMode = 'auto';

function showStatus(message, type = 'success') {
    clearTimeout(statusTimeout); statusMessage.textContent = message;
    statusMessage.className = `status-message ${type === 'error' ? 'bg-red-900/50' : 'bg-green-900/50'}`;
    statusTimeout = setTimeout(() => statusMessage.classList.add('hidden'), 4000);
}
function imageUrl(item) { return item.image?.url || (item.entry_type === 'collection' ? '/banner_folder.png' : '/banner_video.png'); }
function card(item) {
    const visualType = item.entry_type === 'collection' ? 'folder' : 'video';
    const element = document.createElement('button'); element.className = `media-item ${visualType}`; element.title = item.title;
    const image = document.createElement('img'); image.className = 'banner'; image.alt = ''; image.src = imageUrl(item);
    image.onerror = () => { image.src = item.entry_type === 'collection' ? '/banner_folder.png' : '/banner_video.png'; };
    const title = document.createElement('div'); title.className = 'file-name'; title.textContent = item.title;
    element.append(image, title);
    element.onclick = () => item.entry_type === 'collection' ? navigate(item.id, item.title) : selectMedia(item.id);
    return element;
}
function renderBreadcrumbs() {
    breadcrumbs.innerHTML = '';
    [{ id: null, title: 'Início' }, ...trail].forEach((entry, index) => {
        if (index) { const separator = document.createElement('li'); separator.textContent = '›'; breadcrumbs.appendChild(separator); }
        const li = document.createElement('li'); const button = document.createElement('button'); button.className = 'brand hover:underline'; button.textContent = entry.title;
        button.onclick = () => { trail = trail.slice(0, index); navigate(entry.id, null, false); }; li.appendChild(button); breadcrumbs.appendChild(li);
    });
}
async function navigate(parentId = null, title = null, push = true) {
    if (!sourceId) return;
    if (push && parentId !== null) trail.push({ id: parentId, title });
    renderBreadcrumbs(); folders.innerHTML = '<p>Carregando…</p>'; videos.innerHTML = '';
    const params = new URLSearchParams({ source_id: sourceId }); if (parentId !== null) params.set('parent_id', parentId);
    try {
        const response = await fetch(`/api/catalog?${params}`); const data = await response.json(); if (!response.ok) throw new Error(data.detail);
        const collections = data.items.filter(item => item.entry_type === 'collection');
        const playable = data.items.filter(item => item.entry_type === 'playable');
        folders.innerHTML = ''; videos.innerHTML = '';
        collections.forEach(item => folders.appendChild(card(item))); playable.forEach(item => videos.appendChild(card(item)));
        if (!collections.length) folders.innerHTML = '<p class="text-gray-500">Nenhuma coleção.</p>';
        if (!playable.length) videos.innerHTML = '<p class="text-gray-500">Nenhum vídeo.</p>';
    } catch (error) { folders.innerHTML = ''; videos.innerHTML = ''; showStatus(error.message || 'Origem indisponível.', 'error'); }
}
function selectMedia(mediaId) { socket.emit('host_set_video', { source_id: sourceId, media_id: mediaId }); showStatus('Mídia selecionada.'); }
searchForm.onsubmit = async event => {
    event.preventDefault(); const query = searchInput.value.trim(); if (!query || !sourceId) return;
    folders.innerHTML = '<p>Buscando…</p>'; videos.innerHTML = '';
    try {
        const response = await fetch(`/api/search?${new URLSearchParams({source_id: sourceId, q: query})}`);
        const data = await response.json(); if (!response.ok) throw new Error(data.detail);
        folders.innerHTML = ''; videos.innerHTML = '';
        data.items.filter(item => item.entry_type === 'collection').forEach(item => folders.appendChild(card(item)));
        data.items.filter(item => item.entry_type === 'playable').forEach(item => videos.appendChild(card(item)));
        if (!folders.children.length) folders.innerHTML = '<p class="text-gray-500">Nenhuma coleção.</p>';
        if (!videos.children.length) videos.innerHTML = '<p class="text-gray-500">Nenhum vídeo.</p>';
    } catch (error) { folders.innerHTML = ''; videos.innerHTML = ''; showStatus(error.message || 'Busca indisponível.', 'error'); }
};
socket.on('media_selection_error', data => showStatus(data.message, 'error'));
sourceSelect.onchange = () => { sourceId = sourceSelect.value; trail = []; navigate(); };

async function loadSources() {
    try { const response = await fetch('/api/sources'); const data = await response.json(); if (!response.ok) throw new Error();
        sourceSelect.innerHTML = ''; data.sources.forEach(source => { const option = document.createElement('option'); option.value = source.id; option.textContent = source.label; sourceSelect.appendChild(option); });
        sourceId = data.sources[0]?.id || null; if (sourceId) navigate();
    } catch (_) { showStatus('Não foi possível carregar as origens.', 'error'); }
}
fetch('/api/get_ip').then(r => r.json()).then(data => { document.getElementById('invite-link-field').value = data.link; });
document.getElementById('copy-link-btn').onclick = async () => { const field = document.getElementById('invite-link-field'); await navigator.clipboard.writeText(field.value); showStatus('Link copiado.'); };
const rtcDescriptions = { off: 'Usa somente STUN.', auto: 'Usa TURN como fallback.', relay: 'Todo o tráfego WebRTC passa pelo TURN.' };
async function loadRtc() { const response = await fetch('/api/rtc_mode'); const data = await response.json(); previousRtcMode = data.mode; rtcModeSelect.value = data.mode; rtcModeDescription.textContent = rtcDescriptions[data.mode]; for (const option of rtcModeSelect.options) option.disabled = !data.turnConfigured && option.value !== 'off'; }
rtcModeSelect.onchange = async () => { const mode = rtcModeSelect.value; rtcModeDescription.textContent = rtcDescriptions[mode]; const response = await fetch('/api/rtc_mode', { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({mode}) }); if (response.ok) { previousRtcMode = mode; rtcModeStatus.textContent = 'Modo salvo.'; } else { rtcModeSelect.value = previousRtcMode; rtcModeStatus.textContent = 'Não foi possível salvar.'; } };
loadSources(); loadRtc();
