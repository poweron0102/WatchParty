import { loadRtcConfig } from './webrtc.js';
import { setIPv6First } from './utils.js';
import { showNotification } from './notifications.js';

export const SCREEN_SHARE_VIDEO_ID = 'screen-share';
export const screenSharePeerConnections = {};
export const screenShareState = {
    mode: 'idle',
    sessionId: null,
    error: null
};

let screenStream = null;
let isStopping = false;
const pendingIceCandidates = {};
const connectionMeta = {};
const retryTimers = {};
const MAX_RETRIES = 1;
const RETRY_DELAY_MS = 900;

function setScreenShareMode(mode, error = null) {
    screenShareState.mode = mode;
    screenShareState.error = error;
}

export function isScreenShareVideo(video) {
    return video === SCREEN_SHARE_VIDEO_ID;
}

export function isScreenShareActive() {
    return ['starting', 'sharing', 'receiving', 'stopping'].includes(screenShareState.mode) ||
        !!screenShareState.sessionId ||
        !!screenStream ||
        Object.keys(screenSharePeerConnections).length > 0;
}

export function getScreenShareSessionId() {
    return screenShareState.sessionId;
}

export function setScreenShareSession(sessionId, mode = 'receiving') {
    if (!sessionId) return;

    if (screenShareState.sessionId && screenShareState.sessionId !== sessionId) {
        closeAllScreenShareConnections();
    }

    screenShareState.sessionId = sessionId;
    setScreenShareMode(mode);
}

export function getScreenStream() {
    return screenStream;
}

export function setScreenStream(stream) {
    screenStream = stream;
    if (stream) setScreenShareMode('sharing');
}

function clearScreenShareState() {
    screenStream = null;
    screenShareState.sessionId = null;
    setScreenShareMode('idle');
}

function candidatePrefersIPv6(candidate) {
    const ip = candidate?.candidate?.split(' ')[4] || '';
    return ip.includes(':');
}

function emitScreenShareCandidate(socket, targetSid, candidate, sessionId) {
    const emitPayload = () => socket.emit('webrtc_signal', {
        target_sid: targetSid,
        payload: {
            type: 'ice_candidate',
            candidate,
            purpose: 'screen',
            session_id: sessionId
        }
    });

    if (candidatePrefersIPv6(candidate)) emitPayload();
    else setTimeout(emitPayload, 300);
}

async function addIceCandidateOrQueue(sid, candidate) {
    const pc = screenSharePeerConnections[sid];
    if (!pc) {
        pendingIceCandidates[sid] = pendingIceCandidates[sid] || [];
        pendingIceCandidates[sid].push(candidate);
        return;
    }

    if (!pc.remoteDescription || !pc.remoteDescription.type) {
        pendingIceCandidates[sid] = pendingIceCandidates[sid] || [];
        pendingIceCandidates[sid].push(candidate);
        return;
    }

    try {
        await pc.addIceCandidate(new RTCIceCandidate(candidate));
    } catch (error) {
        console.error('Erro ao adicionar candidato ICE (tela):', error);
    }
}

async function flushPendingIceCandidates(sid) {
    const queuedCandidates = pendingIceCandidates[sid] || [];
    pendingIceCandidates[sid] = [];

    for (const candidate of queuedCandidates) {
        await addIceCandidateOrQueue(sid, candidate);
    }
}

function closeAllScreenShareConnections() {
    for (const sid of Object.keys(screenSharePeerConnections)) {
        closeScreenShareConnection(sid);
    }
}

export function closeScreenShareConnection(sid) {
    if (retryTimers[sid]) {
        clearTimeout(retryTimers[sid]);
        delete retryTimers[sid];
    }

    if (screenSharePeerConnections[sid]) {
        try {
            const pc = screenSharePeerConnections[sid];
            pc.onicecandidate = null;
            pc.oniceconnectionstatechange = null;
            pc.onconnectionstatechange = null;
            pc.ontrack = null;
            pc.close();
        } catch (error) {
            console.warn('Erro ao fechar conexao de tela:', error);
        }
        delete screenSharePeerConnections[sid];
    }

    delete pendingIceCandidates[sid];
    delete connectionMeta[sid];
}

function attachStreamToPlayer(player, stream, muted) {
    player.source = { type: 'video', sources: [] };
    player.media.srcObject = stream;
    player.muted = muted;
    player.play().catch(error => console.warn('Autoplay da tela falhou:', error));
}

function detachPlayerStream(player) {
    if (player.media.srcObject) {
        player.media.srcObject.getTracks().forEach(track => {
            if (track.readyState !== 'ended') track.stop();
        });
        player.media.srcObject = null;
    }

    player.source = { type: 'video', sources: [] };
    player.pause();
    player.muted = false;
}

export async function startScreenShare(socket, player, screenShareBtn) {
    if (screenStream) return true;

    if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
        setScreenShareMode('error', 'display-media-unavailable');
        showNotification('A transmissão de tela exige HTTPS, localhost ou um navegador compatível.', 'warning');
        return false;
    }

    try {
        setScreenShareMode('starting');
        await loadRtcConfig();

        const stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
        setScreenStream(stream);
        attachStreamToPlayer(player, stream, true);

        if (screenShareBtn) {
            screenShareBtn.classList.add('sharing');
            screenShareBtn.textContent = 'Parar Transmissão';
        }

        const stopWhenCaptureEnds = () => {
            if (!isStopping && screenStream === stream) {
                stopScreenShare(socket, player, screenShareBtn, { value: true });
            }
        };

        stream.getTracks().forEach(track => {
            track.addEventListener('ended', stopWhenCaptureEnds, { once: true });
        });

        socket.emit('start_screen_share');
        return true;
    } catch (error) {
        console.error('Erro ao iniciar a transmissão de tela:', error);
        clearScreenShareState();
        setScreenShareMode('error', error);
        if (error?.name === 'NotAllowedError') {
            showNotification('Não foi possível iniciar a transmissão de tela. Permissão negada?', 'warning');
        }
        return false;
    }
}

export function stopScreenShare(socket, player, screenShareBtn, isHostRef, options = {}) {
    const sessionId = options.sessionId || screenShareState.sessionId;
    const hasActivePlayerStream = !!player.media.srcObject;
    const hadScreenShare = !!screenStream ||
        hasActivePlayerStream ||
        Object.keys(screenSharePeerConnections).length > 0 ||
        screenShareState.mode !== 'idle';

    if (!hadScreenShare || isStopping) return;
    if (options.sessionId && screenShareState.sessionId && options.sessionId !== screenShareState.sessionId) return;

    isStopping = true;
    setScreenShareMode('stopping');

    const shouldEmitStop = options.emit !== false && !!isHostRef?.value && !!screenStream;
    const streamToStop = screenStream;
    screenStream = null;

    if (streamToStop) {
        streamToStop.getTracks().forEach(track => {
            if (track.readyState !== 'ended') track.stop();
        });
    }

    closeAllScreenShareConnections();
    detachPlayerStream(player);

    if (screenShareBtn) {
        screenShareBtn.classList.remove('sharing');
        screenShareBtn.textContent = 'Transmitir Tela';
    }

    if (shouldEmitStop) {
        socket.emit('stop_screen_share', { session_id: sessionId });
    }

    clearScreenShareState();
    isStopping = false;
}

function scheduleScreenShareRetry(targetSid, stream, socket, sessionId, retryCount) {
    if (retryTimers[targetSid]) return;

    closeScreenShareConnection(targetSid);

    if (!stream || retryCount >= MAX_RETRIES || screenShareState.sessionId !== sessionId) return;

    retryTimers[targetSid] = setTimeout(() => {
        delete retryTimers[targetSid];
        if (screenStream && screenShareState.sessionId === sessionId) {
            createScreenShareConnection(targetSid, stream, socket, sessionId, retryCount + 1);
        }
    }, RETRY_DELAY_MS);
}

export async function createScreenShareConnection(targetSid, stream, socket, sessionId, retryCount = 0) {
    if (!sessionId || !stream) return;

    let rtcConfig;
    try {
        rtcConfig = await loadRtcConfig();
    } catch (_error) {
        return;
    }
    setScreenShareSession(sessionId, 'sharing');

    if (screenSharePeerConnections[targetSid]) closeScreenShareConnection(targetSid);

    const pc = new RTCPeerConnection(rtcConfig);
    screenSharePeerConnections[targetSid] = pc;
    connectionMeta[targetSid] = { sessionId, role: 'host', retryCount };

    stream.getTracks().forEach(track => pc.addTrack(track, stream));

    pc.onicecandidate = (event) => {
        if (event.candidate) {
            emitScreenShareCandidate(socket, targetSid, event.candidate, sessionId);
        }
    };

    pc.oniceconnectionstatechange = () => {
        if (pc.iceConnectionState === 'failed') {
            scheduleScreenShareRetry(targetSid, stream, socket, sessionId, retryCount);
        }
    };

    pc.onconnectionstatechange = () => {
        if (pc.connectionState === 'failed') {
            scheduleScreenShareRetry(targetSid, stream, socket, sessionId, retryCount);
        } else if (pc.connectionState === 'closed') {
            closeScreenShareConnection(targetSid);
        }
    };

    const offer = await pc.createOffer();
    offer.sdp = setIPv6First(offer.sdp);
    await pc.setLocalDescription(offer);
    socket.emit('webrtc_signal', {
        target_sid: targetSid,
        payload: {
            type: 'offer',
            sdp: pc.localDescription,
            purpose: 'screen',
            session_id: sessionId
        }
    });
}

export async function handleScreenSignal(payload, socket, player) {
    const senderSid = payload.sender_sid;
    const sessionId = payload.session_id;

    if (!senderSid || !sessionId) return;
    if (!screenShareState.sessionId || screenShareState.sessionId !== sessionId) return;

    let pc = screenSharePeerConnections[senderSid];
    const meta = connectionMeta[senderSid];

    if (meta && meta.sessionId !== sessionId) return;

    switch (payload.type) {
        case 'offer':
            let rtcConfig;
            try {
                rtcConfig = await loadRtcConfig();
            } catch (_error) {
                return;
            }
            if (pc) closeScreenShareConnection(senderSid);

            pc = new RTCPeerConnection(rtcConfig);
            screenSharePeerConnections[senderSid] = pc;
            connectionMeta[senderSid] = { sessionId, role: 'receiver', retryCount: 0 };

            pc.onicecandidate = (event) => {
                if (event.candidate) {
                    emitScreenShareCandidate(socket, senderSid, event.candidate, sessionId);
                }
            };

            pc.oniceconnectionstatechange = () => {
                if (pc.iceConnectionState === 'failed') closeScreenShareConnection(senderSid);
            };

            pc.onconnectionstatechange = () => {
                if (['failed', 'closed'].includes(pc.connectionState)) closeScreenShareConnection(senderSid);
            };

            pc.ontrack = (event) => {
                const incomingStream = event.streams[0] || new MediaStream([event.track]);
                if (player.media.srcObject !== incomingStream) {
                    setScreenShareMode('receiving');
                    attachStreamToPlayer(player, incomingStream, false);
                }

                event.track.addEventListener('ended', () => {
                    stopScreenShare(socket, player, null, { value: false }, { emit: false, sessionId });
                }, { once: true });
            };

            await pc.setRemoteDescription(new RTCSessionDescription(payload.sdp));
            await flushPendingIceCandidates(senderSid);

            const answer = await pc.createAnswer();
            answer.sdp = setIPv6First(answer.sdp);
            await pc.setLocalDescription(answer);
            socket.emit('webrtc_signal', {
                target_sid: senderSid,
                payload: {
                    type: 'answer',
                    sdp: pc.localDescription,
                    purpose: 'screen',
                    session_id: sessionId
                }
            });
            break;

        case 'answer':
            if (pc) {
                await pc.setRemoteDescription(new RTCSessionDescription(payload.sdp));
                await flushPendingIceCandidates(senderSid);
            }
            break;

        case 'ice_candidate':
            await addIceCandidateOrQueue(senderSid, payload.candidate);
            break;
    }
}
