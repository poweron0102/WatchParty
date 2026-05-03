// monitorSpeech recebe getters para evitar import circular com webrtc.js
export function monitorSpeech(stream, sid, { getPeerConnections, getLocalStream, getSocketId }) {
    try {
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const source = audioCtx.createMediaStreamSource(stream);
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 256;
        analyser.smoothingTimeConstant = 0.5;
        source.connect(analyser);
        const dataArray = new Uint8Array(analyser.frequencyBinCount);

        const checkAudioLevel = () => {
            const peerConnections = getPeerConnections();
            const localStream = getLocalStream();
            const socketId = getSocketId();

            if (sid !== 'local' && !peerConnections[sid]) return;
            if (sid === 'local' && !localStream) {
                const localItem = document.querySelector(`.user-item[data-sid="${socketId}"]`);
                if (localItem) localItem.classList.remove('is-speaking');
                return;
            }

            analyser.getByteFrequencyData(dataArray);
            let sum = 0;
            for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
            const average = sum / dataArray.length;

            const targetSid = sid === 'local' ? socketId : sid;
            const userItem = document.querySelector(`.user-item[data-sid="${targetSid}"]`);
            if (userItem) {
                if (average > 15) userItem.classList.add('is-speaking');
                else userItem.classList.remove('is-speaking');
            }
            requestAnimationFrame(checkAudioLevel);
        };
        checkAudioLevel();
    } catch (e) {
        console.error("Erro ao iniciar monitoramento de áudio", e);
    }
}
