import { initializeChat } from './chat/chat.js';
import { showNotification } from './modules/notifications.js';
import { setSocketIdGetter, closePeerConnection, handleAudioSignal } from './modules/webrtc.js';
import { closeScreenShareConnection, createScreenShareConnection, getScreenShareSessionId,
         isScreenShareVideo, setScreenShareSession, stopScreenShare, getScreenStream,
         handleScreenSignal } from './modules/screen-share.js';
import { setupDubListeners, handleSyncState, handleSyncEvent, handleForceSync } from './modules/video-sync.js';
import { updateStatusIndicator, setupHostUI } from './modules/host-ui.js';
import { PlayerController } from './modules/player-controller.js';

const socket = io();
const player = new PlayerController(document.getElementById('player'));
player.media.addEventListener('shaka-error', event => {
    const code = event.detail?.code ? ` (código ${event.detail.code})` : '';
    showNotification(`Falha no player${code}.`, 'error');
});
const dubPlayer = { pause(){}, play(){ return Promise.resolve(); }, currentTime: 0 };
const statusIndicator = document.getElementById('status-indicator');
const audioControlsContainer = document.getElementById('audio-controls-container');
const dubSelector = document.getElementById('dub-selector');
const dubVolume = document.getElementById('dub-volume');
const dubDelayInput = document.getElementById('dub-delay');
const hostPanel = document.getElementById('host-panel');
const screenShareBtn = document.getElementById('screen-share-btn');
const closeHostPanelBtn = document.getElementById('close-host-panel-btn');

const isHostRef = { value: false };
let clientState = { users: {} };

const userName = sessionStorage.getItem('userName');
const userPfp = sessionStorage.getItem('userPfp');
if (!userName) window.location.href = '/';

socket.emit('join_room', { name: userName, pfp: userPfp });

setSocketIdGetter(() => socket.id);

document.addEventListener('DOMContentLoaded', () => {
    showNotification(`Bem-vindo à party, <strong>${userName}</strong>!`, 'success');
});

initializeChat(socket, userName, showNotification, () => isHostRef.value);
setupDubListeners(dubSelector, dubVolume, dubDelayInput, dubPlayer, player);
setupHostUI({ socket, player, dubPlayer, dubDelayInput, statusIndicator, hostPanel, screenShareBtn, closeHostPanelBtn, isHostRef });

socket.on('set_host', () => {
    isHostRef.value = true;
    updateStatusIndicator(statusIndicator, true);
    statusIndicator.classList.add('is-host');
    statusIndicator.title = 'Abrir painel do host';
});

socket.on('remove_host', () => {
    isHostRef.value = false;
    updateStatusIndicator(statusIndicator, false);
    statusIndicator.classList.remove('is-host');
    statusIndicator.title = '';
});

socket.on('update_users', (users) => {
    const previousUsers = clientState.users;
    const previousHostSid = Object.keys(previousUsers).find(sid => previousUsers[sid].isHost);

    for (const sid in users) {
        if (!previousUsers[sid] && sid !== socket.id) {
            showNotification(`<strong>${users[sid].name}</strong> entrou na sala.`, 'success');
        }
    }

    const newHostSid = Object.keys(users).find(sid => users[sid].isHost);
    if (newHostSid && newHostSid !== previousHostSid && newHostSid !== socket.id) {
        showNotification(`<strong>${users[newHostSid].name}</strong> agora é o host.`, 'warning');
        if (isHostRef.value && newHostSid !== socket.id) updateStatusIndicator(statusIndicator, false);
    }

    clientState.users = users;
});

socket.on('sync_state', (state) => {
    if (isScreenShareVideo(state.video) && state.session_id) {
        setScreenShareSession(state.session_id, 'receiving');
    }
    handleSyncState(state, player, dubSelector, audioControlsContainer);
});

socket.on('sync_event', (data) => {
    if (data.type === 'set_video' && isScreenShareVideo(data.video)) {
        setScreenShareSession(data.session_id, 'receiving');
    }

    handleSyncEvent(
        data,
        player,
        dubPlayer,
        dubDelayInput,
        isHostRef,
        dubSelector,
        audioControlsContainer,
        getScreenStream,
        (options = {}) => stopScreenShare(socket, player, screenShareBtn, isHostRef, options)
    );
});

socket.on('force_sync', (data) => {
    handleForceSync(data, player, isHostRef, statusIndicator);
});

socket.on('get_host_time', (callback) => {
    if (isHostRef.value) callback({ time: player.currentTime, paused: player.paused });
});

socket.on('peer_disconnected', ({ sid }) => {
    closePeerConnection(sid);
    closeScreenShareConnection(sid);
});

socket.on('initiate_screen_share_to_peer', async ({ target_sid, session_id }) => {
    if (isHostRef.value && getScreenStream() && session_id) {
        await createScreenShareConnection(target_sid, getScreenStream(), socket, session_id);
    }
});

socket.on('screen_share_stopped', (payload = {}) => {
    const stoppedSessionId = payload.session_id;
    const activeSessionId = getScreenShareSessionId();

    if (stoppedSessionId && activeSessionId && stoppedSessionId !== activeSessionId) return;

    stopScreenShare(socket, player, screenShareBtn, isHostRef, { emit: false, sessionId: stoppedSessionId });

    if (!isHostRef.value) {
        showNotification('A transmissão de tela terminou.', 'info');
    }
});

socket.on('webrtc_signal', async (payload) => {
    if (!payload.sender_sid) return;
    if ((payload.purpose || 'audio') === 'screen') {
        return handleScreenSignal(payload, socket, player);
    }
    return handleAudioSignal(payload, socket, userName);
});
