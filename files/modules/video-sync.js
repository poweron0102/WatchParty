import { isVideoFromYoutube } from './utils.js';
import { showNotification } from './notifications.js';

// Shared mutable state — imported as a live reference by host-ui.js
export const syncState = {
    isSyncing: false,
    syncInterval: null,
    syncRequestTime: 0
};

export async function loadMediaTracks(videoPath) {
    try {
        const response = await fetch(`/api/get_subtitles/${videoPath}`);
        if (!response.ok) return { subtitles: [], dubs: [] };
        const data = await response.json();
        return { subtitles: data.subtitles || [], dubs: data.dubs || [] };
    } catch (error) {
        console.error("Erro ao buscar faixas de mídia:", error);
        return { subtitles: [], dubs: [] };
    }
}

export function setupDubControls(dubs, dubSelector, audioControlsContainer) {
    dubSelector.innerHTML = '';
    if (dubs && dubs.length > 1) {
        dubs.forEach(dub => {
            const option = document.createElement('option');
            option.value = dub.lang;
            option.textContent = dub.label;
            option.dataset.src = dub.src || '';
            dubSelector.appendChild(option);
        });
        audioControlsContainer.style.display = 'flex';
    } else {
        audioControlsContainer.style.display = 'none';
    }
}

export function setupDubListeners(dubSelector, dubVolume, dubDelayInput, dubPlayer, player) {
    dubSelector.addEventListener('change', (e) => {
        const selectedOption = e.target.options[e.target.selectedIndex];
        const src = selectedOption.dataset.src;
        if (src) {
            dubPlayer.src = src;
            dubPlayer.currentTime = player.currentTime;
            if (!player.paused) dubPlayer.play();
            player.muted = true;
        } else {
            dubPlayer.src = '';
            player.muted = false;
        }
    });

    dubVolume.addEventListener('input', (e) => {
        dubPlayer.volume = e.target.value;
    });

    dubDelayInput.addEventListener('change', (e) => {
        dubPlayer.currentTime = player.currentTime + parseFloat(e.target.value);
    });
}

export function handleSyncState(state, player, dubSelector, audioControlsContainer) {
    if (!state.video) return;

    syncState.isSyncing = true;

    if (state.video.startsWith('http')) {
        player.source = {
            type: 'video',
            sources: [{
                src: state.video,
                provider: isVideoFromYoutube(state.video) ? 'youtube' : 'html5'
            }]
        };
    } else {
        loadMediaTracks(state.video).then(({ subtitles, dubs }) => {
            player.source = {
                type: 'video',
                sources: [{ src: `/video/${state.video}`, provider: 'html5' }],
                tracks: subtitles
            };
            setupDubControls(dubs, dubSelector, audioControlsContainer);
        });
    }

    player.currentTime = state.time;
    if (state.paused) {
        player.pause();
    } else {
        player.play().catch(() => console.warn('Autoplay bloqueado pelo navegador.'));
    }
    setTimeout(() => { syncState.isSyncing = false; }, 1000);
}

export function handleSyncEvent(data, player, dubPlayer, dubDelayInput, isHostRef, dubSelector, audioControlsContainer, getScreenStream, stopScreenShare) {
    if (isHostRef.value && ['play', 'pause', 'seek'].includes(data.type)) return;

    syncState.isSyncing = true;

    try {
        switch (data.type) {
            case 'set_video':
                if (isHostRef.value && getScreenStream()) stopScreenShare();

                if (player.media.srcObject) {
                    player.media.srcObject.getTracks().forEach(track => track.stop());
                    player.media.srcObject = null;
                }

                if (data.video === 'screen-share') {
                    showNotification("O host iniciou uma transmissão de tela.", "info");
                    player.pause();
                    player.source = { type: 'video', sources: [] };
                    break;
                }

                if (data.video.startsWith('http')) {
                    player.source = {
                        type: 'video',
                        sources: [{ src: data.video, provider: isVideoFromYoutube(data.video) ? 'youtube' : 'html5' }]
                    };
                } else {
                    loadMediaTracks(data.video).then(({ subtitles, dubs }) => {
                        player.source = {
                            type: 'video',
                            sources: [{ src: `/video/${data.video}`, provider: 'html5' }],
                            tracks: subtitles
                        };
                        setupDubControls(dubs, dubSelector, audioControlsContainer);
                    });
                }

                player.pause();
                player.currentTime = 0;
                break;

            case 'play':
                if (!player.muted) dubPlayer.pause(); else dubPlayer.play();
                player.play();
                break;

            case 'pause':
                dubPlayer.pause();
                player.pause();
                break;

            case 'seek':
                if (Math.abs(player.currentTime - data.time) > 1.5) {
                    player.currentTime = data.time;
                }
                dubPlayer.currentTime = player.currentTime + parseFloat(dubDelayInput.value);
                break;
        }
    } catch (e) {
        console.error("Erro ao sincronizar player:", e);
    }

    setTimeout(() => { syncState.isSyncing = false; }, 500);
}

export function handleForceSync(data, player, isHostRef, statusIndicator) {
    if (isHostRef.value || syncState.isSyncing) return;

    const ping = Date.now() - syncState.syncRequestTime;
    const correctedTime = data.time + (ping / 2 / 1000);

    statusIndicator.innerHTML = `Ping: <span class="ping-value">${ping} ms</span>`;

    if (Math.abs(player.currentTime - correctedTime) > 2) {
        syncState.isSyncing = true;
        player.currentTime = correctedTime;
        if (data.paused && !player.paused) player.pause();
        else if (!data.paused && player.paused) player.play();
        setTimeout(() => { syncState.isSyncing = false; }, 500);
    }
}
