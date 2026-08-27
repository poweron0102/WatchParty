import { showNotification } from './notifications.js';
import { isScreenShareVideo } from './screen-share.js';

export const syncState = { isSyncing: false, syncInterval: null, syncRequestTime: 0, currentVideo: null, loadToken: 0 };

export async function loadMediaTracks(selection) {
    const params = new URLSearchParams(selection);
    const response = await fetch(`/api/media?${params}`);
    if (!response.ok) throw new Error('Não foi possível carregar a mídia.');
    return response.json();
}
export function setupDubControls(dubs, dubSelector, audioControlsContainer) {
    dubSelector.innerHTML = '';
    const tracks = [{ label: 'Original', language: 'original', url: '' }, ...(dubs || [])];
    tracks.forEach(track => { const option = document.createElement('option'); option.value = track.language || track.resource_id; option.textContent = track.label; option.dataset.src = track.url || ''; dubSelector.appendChild(option); });
    audioControlsContainer.style.display = tracks.length > 1 ? 'flex' : 'none';
}
export function setupDubListeners(dubSelector, dubVolume, dubDelayInput, dubPlayer, player) {
    dubSelector.addEventListener('change', event => { const src = event.target.options[event.target.selectedIndex].dataset.src; dubPlayer.pause(); dubPlayer.src = src || ''; player.muted = Boolean(src); if (src) { dubPlayer.currentTime = player.currentTime; if (!player.paused) dubPlayer.play().catch(() => {}); } });
    dubVolume.addEventListener('input', event => { dubPlayer.volume = event.target.value; });
    dubDelayInput.addEventListener('change', event => { dubPlayer.currentTime = player.currentTime + parseFloat(event.target.value); });
}
function clearMedia(player, dubPlayer, dubSelector, audioControlsContainer) {
    if (dubPlayer) { dubPlayer.pause(); dubPlayer.removeAttribute('src'); dubPlayer.load(); }
    player.muted = false; setupDubControls([], dubSelector, audioControlsContainer);
}
async function applySelection(selection, player, dubSelector, audioControlsContainer, dubPlayer = null) {
    const token = ++syncState.loadToken; clearMedia(player, dubPlayer, dubSelector, audioControlsContainer);
    const item = await loadMediaTracks(selection); if (token !== syncState.loadToken) return false;
    player.source = { type: 'video', sources: [{ src: item.video.url, type: item.video.content_type, provider: 'html5' }], tracks: (item.subtitles || []).map(track => ({ kind: 'captions', label: track.label, srclang: track.language || 'und', src: track.url, default: track.default })) };
    setupDubControls(item.audio_tracks, dubSelector, audioControlsContainer); return true;
}
export async function handleSyncState(state, player, dubSelector, audioControlsContainer) {
    if (!state.video) return; syncState.isSyncing = true; syncState.currentVideo = state.video;
    try { if (await applySelection(state.video, player, dubSelector, audioControlsContainer)) { player.currentTime = state.time; if (state.paused) player.pause(); else await player.play(); } }
    catch (error) { console.error(error); showNotification(error.message, 'error'); }
    finally { setTimeout(() => { syncState.isSyncing = false; }, 500); }
}
export function handleSyncEvent(data, player, dubPlayer, dubDelayInput, isHostRef, dubSelector, audioControlsContainer, getScreenStream, stopScreenShare) {
    if (isHostRef.value && ['play','pause','seek'].includes(data.type)) return;
    if (isScreenShareVideo(syncState.currentVideo) && ['play','pause','seek'].includes(data.type)) return;
    syncState.isSyncing = true;
    if (data.type === 'set_video') {
        syncState.currentVideo = data.video;
        if (isHostRef.value && getScreenStream()) stopScreenShare({ emit: false, sessionId: data.session_id });
        if (player.media.srcObject) { player.media.srcObject.getTracks().forEach(track => track.stop()); player.media.srcObject = null; }
        if (isScreenShareVideo(data.video)) { syncState.loadToken++; clearMedia(player, dubPlayer, dubSelector, audioControlsContainer); player.pause(); player.source = {type:'video',sources:[]}; showNotification('O host iniciou uma transmissão de tela.', 'info'); }
        else applySelection(data.video, player, dubSelector, audioControlsContainer, dubPlayer).then(ok => { if (ok) { player.pause(); player.currentTime = 0; } }).catch(error => showNotification(error.message, 'error'));
    } else if (data.type === 'play') { if (player.muted) dubPlayer.play().catch(() => {}); player.play().catch(() => {}); }
    else if (data.type === 'pause') { dubPlayer.pause(); player.pause(); }
    else if (data.type === 'seek') { if (Math.abs(player.currentTime - data.time) > 1.5) player.currentTime = data.time; dubPlayer.currentTime = player.currentTime + parseFloat(dubDelayInput.value); }
    setTimeout(() => { syncState.isSyncing = false; }, 500);
}
export function handleForceSync(data, player, isHostRef, statusIndicator) {
    if (isHostRef.value || syncState.isSyncing || player.media.srcObject || isScreenShareVideo(syncState.currentVideo)) return;
    const ping = Date.now() - syncState.syncRequestTime; const correctedTime = data.time + ping / 2000; statusIndicator.innerHTML = `Ping: <span class="ping-value">${ping} ms</span>`;
    if (Math.abs(player.currentTime - correctedTime) > 2) { syncState.isSyncing = true; player.currentTime = correctedTime; if (data.paused) player.pause(); else player.play().catch(() => {}); setTimeout(() => { syncState.isSyncing = false; }, 500); }
}
