import { showNotification } from './notifications.js';
import { setIPv6First } from './utils.js';
import { monitorSpeech } from './audio-monitor.js';

export const rtcConfig = {
    iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
};

export const peerConnections = {};
let localStream = null;

const peerAudioContainer = document.createElement('div');
peerAudioContainer.id = 'peer-audio-container';
document.body.appendChild(peerAudioContainer);

const getters = {
    getPeerConnections: () => peerConnections,
    getLocalStream: () => localStream,
    getSocketId: () => window._socketId || ''
};

export function setSocketIdGetter(fn) {
    getters.getSocketId = fn;
}

export function getLocalStream() {
    return localStream;
}

export async function getLocalMicStream() {
    if (localStream) return localStream;

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        showNotification("Acesso negado: O navegador exige uma conexão segura (HTTPS) para o microfone.", "warning");
        return null;
    }

    try {
        localStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
        const micToggleBtn = document.getElementById('mic-toggle-btn');
        if (micToggleBtn) {
            micToggleBtn.style.display = 'block';
            micToggleBtn.classList.remove('muted');
        }
        monitorSpeech(localStream, 'local', getters);
        return localStream;
    } catch (error) {
        showNotification(`Não foi possível acessar o microfone: ${error.message || 'Permissão negada'}.`, "warning");
        return null;
    }
}

export async function createPeerConnection(targetSid, isInitiator, socket) {
    const stream = await getLocalMicStream();
    if (!stream) return;

    const pc = new RTCPeerConnection(rtcConfig);
    peerConnections[targetSid] = pc;

    stream.getTracks().forEach(track => pc.addTrack(track, stream));

    pc.onicecandidate = (event) => {
        if (event.candidate) {
            const isIPv6 = event.candidate.candidate.split(' ')[4].includes(':');
            const emitPayload = () => socket.emit('webrtc_signal', {
                target_sid: targetSid,
                payload: { type: 'ice_candidate', candidate: event.candidate }
            });
            if (isIPv6) emitPayload();
            else setTimeout(emitPayload, 300);
        }
    };

    pc.ontrack = (event) => {
        if (event.track.kind !== 'audio') return;
        let audioEl = document.getElementById(`peer-audio-${targetSid}`);
        if (!audioEl) {
            audioEl = document.createElement('audio');
            audioEl.id = `peer-audio-${targetSid}`;
            audioEl.autoplay = true;
            peerAudioContainer.appendChild(audioEl);

            const userItem = document.querySelector(`.user-item[data-sid="${targetSid}"]`);
            if (userItem) userItem.classList.add('peer-connected');
            monitorSpeech(event.streams[0], targetSid, getters);
        }
        audioEl.srcObject = event.streams[0];
    };

    pc.onconnectionstatechange = () => {
        if (['disconnected', 'closed', 'failed'].includes(pc.connectionState)) {
            closePeerConnection(targetSid);
        }
    };

    if (isInitiator) {
        const offer = await pc.createOffer();
        offer.sdp = setIPv6First(offer.sdp);
        await pc.setLocalDescription(offer);
        socket.emit('webrtc_signal', {
            target_sid: targetSid,
            payload: { type: 'offer', sdp: pc.localDescription }
        });
    }
}

export function closePeerConnection(sid) {
    if (peerConnections[sid]) {
        peerConnections[sid].close();
        delete peerConnections[sid];

        const audioEl = document.getElementById(`peer-audio-${sid}`);
        if (audioEl) audioEl.remove();

        const userItem = document.querySelector(`.user-item[data-sid="${sid}"]`);
        if (userItem) userItem.classList.remove('peer-connected', 'peer-muted');
    }
    if (Object.keys(peerConnections).length === 0) {
        const micToggleBtn = document.getElementById('mic-toggle-btn');
        if (micToggleBtn) micToggleBtn.style.display = 'none';
        if (localStream) {
            localStream.getTracks().forEach(track => track.stop());
            localStream = null;
        }
    }
}

export async function handleAudioSignal(payload, socket, userName) {
    const senderSid = payload.sender_sid;

    switch (payload.type) {
        case 'request':
            showNotification(`${payload.from_name} quer estabelecer uma conexão de áudio.`, 'info', [
                {
                    text: 'Aceitar',
                    className: 'primary',
                    callback: async () => {
                        socket.emit('webrtc_signal', {
                            target_sid: senderSid,
                            payload: { type: 'request_accepted', from_name: userName }
                        });
                        await createPeerConnection(senderSid, false, socket);
                    }
                },
                {
                    text: 'Recusar',
                    callback: () => {
                        socket.emit('webrtc_signal', {
                            target_sid: senderSid,
                            payload: { type: 'request_declined', from_name: userName }
                        });
                    }
                }
            ]);
            break;

        case 'request_accepted':
            showNotification(`${payload.from_name} aceitou seu pedido. Iniciando conexão...`, 'success');
            await createPeerConnection(senderSid, true, socket);
            break;

        case 'request_declined':
            showNotification(`${payload.from_name} recusou seu pedido.`, 'warning');
            break;

        case 'offer':
            if (peerConnections[senderSid]) {
                await peerConnections[senderSid].setRemoteDescription(new RTCSessionDescription(payload.sdp));
                const answer = await peerConnections[senderSid].createAnswer();
                answer.sdp = setIPv6First(answer.sdp);
                await peerConnections[senderSid].setLocalDescription(answer);
                socket.emit('webrtc_signal', {
                    target_sid: senderSid,
                    payload: { type: 'answer', sdp: peerConnections[senderSid].localDescription }
                });
            }
            break;

        case 'answer':
            if (peerConnections[senderSid]) {
                await peerConnections[senderSid].setRemoteDescription(new RTCSessionDescription(payload.sdp));
            }
            break;

        case 'ice_candidate':
            if (peerConnections[senderSid] && peerConnections[senderSid].remoteDescription) {
                try {
                    await peerConnections[senderSid].addIceCandidate(new RTCIceCandidate(payload.candidate));
                } catch (e) {
                    console.error('Erro ao adicionar candidato ICE:', e);
                }
            }
            break;
    }
}
