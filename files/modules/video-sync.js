import { showNotification } from './notifications.js';
import { isScreenShareVideo } from './screen-share.js';

export const syncState = { isSyncing: false, syncInterval: null, syncRequestTime: 0, currentVideo: null, loadToken: 0, loadingState: null };
let syncResetTimer = null;
let syncVersion = 0;
function beginSync() {
    clearTimeout(syncResetTimer);
    syncState.isSyncing = true;
    return ++syncVersion;
}
function finishSync(version) {
    if (version !== syncVersion) return;
    syncResetTimer = setTimeout(() => { syncState.isSyncing = false; }, 500);
}
export async function loadMediaTracks(selection) {
    const response = await fetch('/api/playback/select', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(selection) });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || 'Não foi possível carregar a mídia.');
    return data;
}
export function setupDubControls() {}
export function setupDubListeners() {}
async function clearMedia(player) { player.muted = false; await player.unload(); }
async function applySelection(selection, player, time, paused) {
    const token = ++syncState.loadToken;
    const target = { time: Math.max(0, Number(time) || 0), paused };
    syncState.loadingState = target;
    try {
        player.muted = false;
        await player.unload();
        if (token !== syncState.loadToken) return false;
        const descriptor = await loadMediaTracks(selection);
        if (token !== syncState.loadToken) return false;
        // Shaka may finish its initial seek after load() resolves. Give it the
        // resume position instead of racing that seek with media.currentTime.
        const startTime = target.time;
        await player.load(descriptor.manifest.url, descriptor, startTime);
        if (token !== syncState.loadToken) return false;
        if (target.time !== startTime) player.currentTime = target.time;
        if (target.paused) player.pause(); else await player.play();
        return token === syncState.loadToken;
    } finally {
        if (token === syncState.loadToken) syncState.loadingState = null;
    }
}
export async function handleSyncState(state, player) {
    if (!state.video) return;
    const version = beginSync();
    syncState.currentVideo = state.video;
    try { await applySelection(state.video, player, state.time, state.paused); }
    catch (error) { console.error(error); showNotification(error.message, 'error'); }
    finally { finishSync(version); }
}
export async function handleSyncEvent(data, player, _dubPlayer, _dubDelay, isHostRef, _selector, _container, getScreenStream, stopScreenShare) {
    if (isHostRef.value && ['play','pause','seek'].includes(data.type)) return;
    if (isScreenShareVideo(syncState.currentVideo) && ['play','pause','seek'].includes(data.type)) return;
    if (!['set_video','play','pause','seek'].includes(data.type)) return;
    // Preserve controls received while selecting/loading, without ending the
    // loading guard or playing the previous episode.
    if (syncState.loadingState && data.type !== 'set_video') {
        if (data.type === 'play') syncState.loadingState.paused = false;
        if (data.type === 'pause') syncState.loadingState.paused = true;
        if (data.type === 'seek') syncState.loadingState.time = Math.max(0, Number(data.time) || 0);
        return;
    }
    const version = beginSync();
    try {
        if (data.type === 'set_video') {
            syncState.currentVideo = data.video;
            if (isHostRef.value && getScreenStream()) stopScreenShare({ emit: false, sessionId: data.session_id });
            if (player.media.srcObject) { player.media.srcObject.getTracks().forEach(track => track.stop()); player.media.srcObject = null; }
            if (isScreenShareVideo(data.video)) {
                syncState.loadToken++;
                syncState.loadingState = null;
                await clearMedia(player);
                player.pause();
                showNotification('O host iniciou uma transmissão de tela.', 'info');
            } else await applySelection(data.video, player, data.time, true);
        } else if (data.type === 'play') await player.play().catch(() => {});
        else if (data.type === 'pause') player.pause();
        else if (data.type === 'seek' && Math.abs(player.currentTime - data.time) > 1.5) player.currentTime = data.time;
    } catch (error) { showNotification(error.message, 'error'); }
    finally { finishSync(version); }
}
export function handleForceSync(data, player, isHostRef, statusIndicator) {
    if (isHostRef.value || syncState.isSyncing || player.media.srcObject || isScreenShareVideo(syncState.currentVideo)) return;
    const ping = Date.now() - syncState.syncRequestTime; const correctedTime = data.time + ping / 2000; statusIndicator.innerHTML = `Ping: <span class="ping-value">${ping} ms</span>`;
    const drift = player.currentTime - correctedTime;
    if (Math.abs(drift) > 2) player.currentTime = correctedTime;
    else if (Math.abs(drift) > 0.25) { player.playbackRate = Math.max(0.9, Math.min(1.1, 1 - drift * 0.08)); setTimeout(() => { player.playbackRate = 1; }, 3000); }
    if (data.paused) player.pause(); else player.play().catch(() => {});
}
