import { showNotification } from './notifications.js';
import { isScreenShareVideo } from './screen-share.js';

export const syncState = { isSyncing: false, syncInterval: null, syncRequestTime: 0, currentVideo: null, loadToken: 0 };
export async function loadMediaTracks(selection) {
    const response = await fetch('/api/playback/select', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(selection) });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || 'Não foi possível carregar a mídia.');
    return data;
}
export function setupDubControls() {}
export function setupDubListeners() {}
function clearMedia(player) { player.muted = false; player.unload(); }
async function applySelection(selection, player) {
    const token = ++syncState.loadToken; player.muted = false; await player.unload();
    const descriptor = await loadMediaTracks(selection); if (token !== syncState.loadToken) return false;
    await player.load(descriptor.manifest.url); return token === syncState.loadToken;
}
export async function handleSyncState(state, player) {
    if (!state.video) return; syncState.isSyncing = true; syncState.currentVideo = state.video;
    try { if (await applySelection(state.video, player)) { player.currentTime = state.time; if (state.paused) player.pause(); else await player.play(); } }
    catch (error) { console.error(error); showNotification(error.message, 'error'); }
    finally { setTimeout(() => { syncState.isSyncing = false; }, 500); }
}
export function handleSyncEvent(data, player, _dubPlayer, _dubDelay, isHostRef, _selector, _container, getScreenStream, stopScreenShare) {
    if (isHostRef.value && ['play','pause','seek'].includes(data.type)) return;
    if (isScreenShareVideo(syncState.currentVideo) && ['play','pause','seek'].includes(data.type)) return;
    syncState.isSyncing = true;
    if (data.type === 'set_video') {
        syncState.currentVideo = data.video;
        if (isHostRef.value && getScreenStream()) stopScreenShare({ emit: false, sessionId: data.session_id });
        if (player.media.srcObject) { player.media.srcObject.getTracks().forEach(track => track.stop()); player.media.srcObject = null; }
        if (isScreenShareVideo(data.video)) { syncState.loadToken++; clearMedia(player); player.pause(); showNotification('O host iniciou uma transmissão de tela.', 'info'); }
        else applySelection(data.video, player).then(ok => { if (ok) { player.pause(); player.currentTime = Number(data.time || 0); } }).catch(error => showNotification(error.message, 'error'));
    } else if (data.type === 'play') player.play().catch(() => {});
    else if (data.type === 'pause') player.pause();
    else if (data.type === 'seek' && Math.abs(player.currentTime - data.time) > 1.5) player.currentTime = data.time;
    setTimeout(() => { syncState.isSyncing = false; }, 500);
}
export function handleForceSync(data, player, isHostRef, statusIndicator) {
    if (isHostRef.value || syncState.isSyncing || player.media.srcObject || isScreenShareVideo(syncState.currentVideo)) return;
    const ping = Date.now() - syncState.syncRequestTime; const correctedTime = data.time + ping / 2000; statusIndicator.innerHTML = `Ping: <span class="ping-value">${ping} ms</span>`;
    const drift = player.currentTime - correctedTime;
    if (Math.abs(drift) > 2) player.currentTime = correctedTime;
    else if (Math.abs(drift) > 0.25) { player.playbackRate = Math.max(0.9, Math.min(1.1, 1 - drift * 0.08)); setTimeout(() => { player.playbackRate = 1; }, 3000); }
    if (data.paused) player.pause(); else player.play().catch(() => {});
}
