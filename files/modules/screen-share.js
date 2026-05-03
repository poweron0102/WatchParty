import { rtcConfig } from './webrtc.js';
import { setIPv6First } from './utils.js';
import { showNotification } from './notifications.js';

export const screenSharePeerConnections = {};
let screenStream = null;

export function getScreenStream() {
    return screenStream;
}

export function setScreenStream(stream) {
    screenStream = stream;
}

export function closeScreenShareConnection(sid) {
    if (screenSharePeerConnections[sid]) {
        screenSharePeerConnections[sid].close();
        delete screenSharePeerConnections[sid];
    }
}

export function stopScreenShare(socket, player, screenShareBtn, isHostRef) {
    if (!isHostRef.value || !screenStream) return;

    screenStream.getTracks().forEach(track => track.stop());
    screenStream = null;

    for (const sid in screenSharePeerConnections) {
        closeScreenShareConnection(sid);
    }

    player.media.srcObject = null;
    player.source = { type: 'video', sources: [] };
    player.pause();
    player.muted = false;

    screenShareBtn.classList.remove('sharing');
    screenShareBtn.textContent = 'Transmitir Tela';

    socket.emit('stop_screen_share');
}

export async function createScreenShareConnection(targetSid, stream, socket) {
    if (screenSharePeerConnections[targetSid]) closeScreenShareConnection(targetSid);

    const pc = new RTCPeerConnection(rtcConfig);
    screenSharePeerConnections[targetSid] = pc;

    stream.getTracks().forEach(track => pc.addTrack(track, stream));

    pc.onicecandidate = (event) => {
        if (event.candidate) {
            const isIPv6 = event.candidate.candidate.split(' ')[4].includes(':');
            const emitPayload = () => socket.emit('webrtc_signal', {
                target_sid: targetSid,
                payload: { type: 'ice_candidate', candidate: event.candidate, purpose: 'screen' }
            });
            if (isIPv6) emitPayload();
            else setTimeout(emitPayload, 300);
        }
    };

    pc.onconnectionstatechange = () => {
        if (['disconnected', 'closed', 'failed'].includes(pc.connectionState)) {
            closeScreenShareConnection(targetSid);
        }
    };

    const offer = await pc.createOffer();
    offer.sdp = setIPv6First(offer.sdp);
    await pc.setLocalDescription(offer);
    socket.emit('webrtc_signal', {
        target_sid: targetSid,
        payload: { type: 'offer', sdp: pc.localDescription, purpose: 'screen' }
    });
}

export async function handleScreenSignal(payload, socket, player) {
    const senderSid = payload.sender_sid;
    let pc = screenSharePeerConnections[senderSid];

    switch (payload.type) {
        case 'offer':
            if (pc) closeScreenShareConnection(senderSid);

            pc = new RTCPeerConnection(rtcConfig);
            screenSharePeerConnections[senderSid] = pc;

            pc.onicecandidate = (event) => {
                if (event.candidate) {
                    const isIPv6 = event.candidate.candidate.split(' ')[4].includes(':');
                    const emitPayload = () => socket.emit('webrtc_signal', {
                        target_sid: senderSid,
                        payload: { type: 'ice_candidate', candidate: event.candidate, purpose: 'screen' }
                    });
                    if (isIPv6) emitPayload();
                    else setTimeout(emitPayload, 300);
                }
            };

            pc.ontrack = (event) => {
                if (player.media.srcObject !== event.streams[0]) {
                    player.source = { type: 'video', sources: [] };
                    player.media.srcObject = event.streams[0];
                    player.muted = false;
                    player.play().catch(e => console.warn("Autoplay da tela falhou", e));
                }
            };

            await pc.setRemoteDescription(new RTCSessionDescription(payload.sdp));
            const answer = await pc.createAnswer();
            answer.sdp = setIPv6First(answer.sdp);
            await pc.setLocalDescription(answer);
            socket.emit('webrtc_signal', {
                target_sid: senderSid,
                payload: { type: 'answer', sdp: pc.localDescription, purpose: 'screen' }
            });
            break;

        case 'answer':
            if (pc) await pc.setRemoteDescription(new RTCSessionDescription(payload.sdp));
            break;

        case 'ice_candidate':
            if (pc && pc.remoteDescription) {
                await pc.addIceCandidate(new RTCIceCandidate(payload.candidate)).catch(e =>
                    console.error('Erro ao adicionar candidato ICE (tela):', e)
                );
            }
            break;
    }
}
