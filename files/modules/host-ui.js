import { showNotification } from './notifications.js';
import { stopScreenShare, getScreenStream, setScreenStream, createScreenShareConnection } from './screen-share.js';
import { peerConnections, getLocalStream } from './webrtc.js';
import { syncState } from './video-sync.js';

export function updateStatusIndicator(statusIndicator, isHost) {
    if (isHost) {
        statusIndicator.innerHTML = `<span class="host-label">⭐ Você é o Host</span>`;
    } else {
        statusIndicator.innerHTML = `Ping: <span class="ping-value">-- ms</span>`;
    }
}

export function setupHostUI({ socket, player, dubPlayer, dubDelayInput, statusIndicator, hostPanel, screenShareBtn, closeHostPanelBtn, isHostRef }) {
    // Host panel toggle
    statusIndicator.addEventListener('click', () => {
        if (isHostRef.value) hostPanel.style.display = 'block';
    });

    closeHostPanelBtn.addEventListener('click', () => {
        hostPanel.style.display = 'none';
    });

    // Screen share button
    screenShareBtn.addEventListener('click', async () => {
        hostPanel.style.display = 'none';
        if (getScreenStream()) {
            stopScreenShare(socket, player, screenShareBtn, isHostRef);
            return;
        }

        try {
            const stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });

            player.source = { type: 'video', sources: [] };
            setScreenStream(stream);

            player.media.srcObject = stream;
            player.muted = true;
            player.play();

            screenShareBtn.classList.add('sharing');
            screenShareBtn.textContent = 'Parar Transmissão';

            socket.emit('start_screen_share');

            stream.getVideoTracks()[0].onended = () => stopScreenShare(socket, player, screenShareBtn, isHostRef);

        } catch (error) {
            console.error("Erro ao iniciar a transmissão de tela:", error);
            showNotification("Não foi possível iniciar a transmissão de tela. Permissão negada?", "warning");
        }
    });

    // Player event listeners
    player.on('play', () => {
        if (isHostRef.value && !syncState.isSyncing) {
            if (!player.muted) dubPlayer.pause(); else dubPlayer.play();
            socket.emit('host_sync', { type: 'play', time: player.currentTime });
            return;
        }
        if (!isHostRef.value) {
            if (syncState.syncInterval) clearInterval(syncState.syncInterval);
            syncState.syncInterval = setInterval(() => {
                if (!player.paused) {
                    syncState.syncRequestTime = Date.now();
                    socket.emit('request_sync');
                }
            }, 3000);
        }
    });

    player.on('pause', () => {
        if (isHostRef.value && !syncState.isSyncing) {
            dubPlayer.pause();
            socket.emit('host_sync', { type: 'pause', time: player.currentTime });
            return;
        }
        if (!isHostRef.value) {
            if (syncState.syncInterval) {
                clearInterval(syncState.syncInterval);
                syncState.syncInterval = null;
            }
        }
    });

    player.on('seeked', () => {
        if (isHostRef.value && !syncState.isSyncing) {
            dubPlayer.currentTime = player.currentTime + parseFloat(dubDelayInput.value);
            socket.emit('host_sync', { type: 'seek', time: player.currentTime });
        }
    });

    // Mic toggle (button is injected by chat module into the DOM)
    document.addEventListener('click', (e) => {
        const micToggleBtn = e.target.closest('#mic-toggle-btn');
        const localStream = getLocalStream();
        if (micToggleBtn && localStream) {
            const isMuted = micToggleBtn.classList.contains('muted');
            localStream.getAudioTracks().forEach(track => { track.enabled = isMuted; });
            micToggleBtn.classList.toggle('muted');
            micToggleBtn.title = isMuted ? 'Mutar microfone' : 'Ativar microfone';
        }
    });

    // Peer mute toggle
    document.addEventListener('togglePeerMute', (e) => {
        const sid = e.detail.sid;
        const audioEl = document.getElementById(`peer-audio-${sid}`);
        const userItem = document.querySelector(`.user-item[data-sid="${sid}"]`);
        if (audioEl && userItem) {
            audioEl.muted = !audioEl.muted;
            userItem.classList.toggle('peer-muted', audioEl.muted);
            const muteBtn = userItem.querySelector('.peer-mute-btn');
            if (muteBtn) muteBtn.classList.toggle('muted', audioEl.muted);
        }
    });

    // Peer ping stats
    document.addEventListener('requestPeerPing', async (e) => {
        const sid = e.detail.sid;
        const pc = peerConnections[sid];
        if (!pc) return;

        try {
            const stats = await pc.getStats();
            let ping = null;
            let localCandidateId = null;
            let remoteCandidateId = null;

            stats.forEach(report => {
                if (report.type === 'candidate-pair' && report.state === 'succeeded') {
                    ping = report.currentRoundTripTime ? report.currentRoundTripTime * 1000 : null;
                    localCandidateId = report.localCandidateId;
                    remoteCandidateId = report.remoteCandidateId;
                }
            });

            let localType = 'Desconhecido', remoteType = 'Desconhecido';
            let protocol = 'Desconhecido';
            let localIpVersion = 'Unknown', remoteIpVersion = 'Unknown';

            if (localCandidateId && remoteCandidateId) {
                const localCandidate = stats.get(localCandidateId);
                const remoteCandidate = stats.get(remoteCandidateId);
                if (localCandidate) {
                    localType = localCandidate.candidateType;
                    protocol = localCandidate.protocol;
                    const ip = localCandidate.address || localCandidate.ip || '';
                    if (ip) localIpVersion = ip.includes(':') ? 'IPv6' : 'IPv4';
                }
                if (remoteCandidate) {
                    remoteType = remoteCandidate.candidateType;
                    const ip = remoteCandidate.address || remoteCandidate.ip || '';
                    if (ip) remoteIpVersion = ip.includes(':') ? 'IPv6' : 'IPv4';
                }
            }

            document.dispatchEvent(new CustomEvent('receivePeerPing', {
                detail: { sid, stats: { ping, localType, remoteType, protocol, localIpVersion, remoteIpVersion } }
            }));
        } catch {
            document.dispatchEvent(new CustomEvent('receivePeerPing', { detail: { sid, stats: null } }));
        }
    });
}

