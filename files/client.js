// /files/client.js

import { initializeChat } from './chat/chat.js';

// --- Conexão e Elementos DOM ---
const socket = io();
// Inicializa o Plyr. Ele substitui o elemento <video> padrão por um mais robusto.
const player = new Plyr('#player', {
    tooltips: { controls: true, seek: true }
});
const dubPlayer = document.getElementById('dub-player');
const statusIndicator = document.getElementById('status-indicator');
const audioControlsContainer = document.getElementById('audio-controls-container');
const dubSelector = document.getElementById('dub-selector');
const dubVolume = document.getElementById('dub-volume');
const dubDelayInput = document.getElementById('dub-delay');


// --- Estado do Cliente ---
let isHost = false;
let isSyncing = false; // Flag para evitar loops de eventos
let syncInterval = null; // intervalo de sincronização
let syncRequestTime = 0; // Para calcular o ping
let clientState = { users: {} }; // Para rastrear o estado e detectar mudanças

// --- Pega dados do "Login" ---
const userName = sessionStorage.getItem('userName');
const userPfp = sessionStorage.getItem('userPfp');

// Se não tiver nome, volta para a página inicial
if (!userName) {
    window.location.href = '/';
}

// --- Envia evento de "Entrar na Sala" ---
socket.emit('join_room', { name: userName, pfp: userPfp });

// --- Sistema de Notificações ---
function createNotificationContainer() {
    const container = document.createElement('div');
    container.id = 'notification-container';
    document.body.appendChild(container);
    return container;
}

function isVideoFromYoutube(videoURL) {
    if (!videoURL || typeof videoURL !== 'string') return false;
    let url = videoURL.trim();
    // adiciona protocolo se ausente para permitir uso do URL parser
    if (!/^[a-zA-Z][a-zA-Z\d+\-.]*:\/\//.test(url)) {
        url = 'https://' + url;
    }

    try {
        const u = new URL(url);
        const host = u.hostname.toLowerCase();

        // Hosts válidos do YouTube
        const isYoutuBe = host === 'youtu.be' || host.endsWith('.youtu.be');
        const isYoutubeDomain =
            host === 'youtube.com' ||
            host.endsWith('.youtube.com') ||
            host === 'youtube-nocookie.com' ||
            host.endsWith('.youtube-nocookie.com');

        if (isYoutuBe) {
            // youtu.be/<id>
            return !!u.pathname.replace(/\//g, '');
        }

        if (!isYoutubeDomain) return false;

        const path = u.pathname;
        // youtube.com/watch?v=ID
        if (u.searchParams.has('v')) return true;
        // /embed/ID , /v/ID , /shorts/ID
        return /^\/(embed|v|shorts)\/[^/]+/.test(path);

    } catch (e) {
        return false;
    }
}


const notificationContainer = createNotificationContainer();

function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;

    const icons = {
        info: `<svg class="notification-icon" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd"></path></svg>`,
        success: `<svg class="notification-icon" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"></path></svg>`,
        warning: `<svg class="notification-icon" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM10 5a1 1 0 011 1v3a1 1 0 11-2 0V6a1 1 0 011-1zm1 5a1 1 0 10-2 0v2a1 1 0 102 0v-2z" clip-rule="evenodd"></path></svg>`
    };

    notification.innerHTML = `
        ${icons[type] || icons.info}
        <div class="notification-content">${message}</div>
    `;

    notificationContainer.appendChild(notification);

    // Remove a notificação após a animação de fadeOut terminar (5s)
    setTimeout(() => {
        notification.remove();
    }, 5000);
}

// Exemplo de notificação ao entrar
document.addEventListener('DOMContentLoaded', () => {
    showNotification(`Bem-vindo à party, <strong>${userName}</strong>!`, 'success');
});

// --- Inicializa o Módulo de Chat ---
initializeChat(socket, userName, showNotification);

// --- Funções de UI ---
function updateStatusIndicator() {
    if (isHost) {
        statusIndicator.innerHTML = `<span class="host-label">⭐ Você é o Host</span>`;
    } else {
        // O texto do ping será atualizado pelo evento 'force_sync'
        statusIndicator.innerHTML = `Ping: <span class="ping-value">-- ms</span>`;
    }
}

// --- Listeners de Eventos do Socket.IO ---

socket.on('set_host', () => {
    isHost = true;
    updateStatusIndicator();
    console.log("Você foi definido como o HOST!");
    // Oculta o botão do painel do host se o usuário não for o host
});

socket.on('update_users', (users) => {
    const previousUsers = clientState.users;
    const previousHostSid = Object.keys(previousUsers).find(sid => previousUsers[sid].isHost);

    // Detectar novos usuários
    for (const sid in users) {
        if (!previousUsers[sid]) {
            // Não notificar a própria entrada
            if (sid !== socket.id) {
                showNotification(`<strong>${users[sid].name}</strong> entrou na sala.`, 'success');
            }
        }
    }

    // Detectar mudança de host
    const newHostSid = Object.keys(users).find(sid => users[sid].isHost);
    if (newHostSid && newHostSid !== previousHostSid) {
        const wasHost = isHost;
        const newHostName = users[newHostSid].name;
        // Não notificar se você se tornou o host (já tem o log no console)
        if (newHostSid !== socket.id) {
            showNotification(`<strong>${newHostName}</strong> agora é o host.`, 'warning');
        }
        if (wasHost && newHostSid !== socket.id) updateStatusIndicator();
    }

    clientState.users = users; // Atualiza o estado
});

async function loadMediaTracks(videoPath) {
    try {
        const response = await fetch(`/api/get_subtitles/${videoPath}`);
        console.log("Resposta do servidor:", response);
        if (!response.ok) return { subtitles: [], dubs: [] };
        const data = await response.json();
        console.log("Resposta do servidor processada:", data);
        return {
            subtitles: data.subtitles || [],
            dubs: data.dubs || []
        };
    } catch (error) {
        console.error("Erro ao buscar faixas de mídia:", error);
        return { subtitles: [], dubs: [] };
    }
}

function setupDubControls(dubs) {
    // Limpa opções anteriores
    dubSelector.innerHTML = '';

    if (dubs && dubs.length > 1) {
        dubs.forEach(dub => {
            const option = document.createElement('option');
            option.value = dub.lang;
            option.textContent = dub.label;
            option.dataset.src = dub.src || ''; // Armazena a URL no dataset
            dubSelector.appendChild(option);
        });
        audioControlsContainer.style.display = 'flex';
    } else {
        // Esconde os controles se não houver dublagens
        audioControlsContainer.style.display = 'none';
    }
}

dubSelector.addEventListener('change', (e) => {
    const selectedOption = e.target.options[e.target.selectedIndex];
    const src = selectedOption.dataset.src;

    if (src) {
        dubPlayer.src = src;
        dubPlayer.currentTime = player.currentTime;
        if (!player.paused) dubPlayer.play();
        player.muted = true;
    } else { // Áudio original
        dubPlayer.src = '';
        player.muted = false;
    }
});

dubVolume.addEventListener('input', (e) => {
    dubPlayer.volume = e.target.value;
});

dubDelayInput.addEventListener('change', (e) => {
    // Ao mudar o delay, ajusta o tempo da dublagem imediatamente
    dubPlayer.currentTime = player.currentTime + parseFloat(e.target.value);
});
socket.on('sync_state', (state) => {
    console.log({state});
    if (state.video) {
        console.log(`Sincronizando com estado: ${state.video} @ ${state.time}s`);
        isSyncing = true;

        // Verifica se é uma URL do YouTube ou um arquivo local
        if (state.video.startsWith('http')) {
            player.source = {
                type: 'video',
                sources: [{ src: state.video, provider: 'youtube' }]
            };
        } else {
            // Busca as legendas antes de configurar a fonte do player para arquivos locais
            loadMediaTracks(state.video).then(({ subtitles, dubs }) => {
                console.log("Legendas encontradas:", subtitles);
                player.source = {
                    type: 'video',
                    sources: [{ src: `/video/${state.video}` }],
                    tracks: subtitles
                };
                setupDubControls(dubs);
            });
        }

        player.currentTime = state.time;
        if (state.paused) {
            player.pause();
        } else {
            // O play() pode falhar se o usuário não interagiu com a página ainda.
            player.play().catch(() => console.warn('Autoplay bloqueado pelo navegador.'));
        }
        // Desativa a flag após um tempo para permitir o player "assentar" no novo estado
        setTimeout(() => { isSyncing = false; }, 1000);
    }
});

socket.on('sync_event', (data) => {
    // O host não deve reagir aos seus próprios eventos de play/pause/seek
    if (isHost && ['play', 'pause', 'seek'].includes(data.type)) {
        return;
    }
    console.log('Recebido evento de sync:', data);

    // Ativa a flag para impedir que este evento dispare um novo evento de 'play/pause/seek'
    isSyncing = true;

    try {
        switch(data.type) {
            case 'set_video':
                if (data.video.startsWith('http')) {

                    if (isVideoFromYoutube(data.video)) {
                        player.source = {
                            type: 'video',
                            sources: [{src: data.video, provider: 'youtube'}]
                        };
                    }
                    else {
                        player.source = {
                            type: 'video',
                            sources: [{src: data.video}]
                        };
                    }

                } else {
                    // Busca as legendas e então atualiza o player para arquivos locais
                    loadMediaTracks(data.video).then(({ subtitles, dubs }) => {
                        console.log("Legendas encontradas:", subtitles);
                        player.source = {
                            type: 'video',
                            sources: [{ src: `/video/${data.video}` }],
                            tracks: subtitles
                        };
                        setupDubControls(dubs);
                    });
                }

                player.pause();
                player.currentTime = 0;
                break;
            case 'play':
                // Sincroniza o player de dublagem também
                if (!player.muted) dubPlayer.pause(); else dubPlayer.play();
                player.play();
                break;
            case 'pause':
                // Sincroniza o player de dublagem também
                dubPlayer.pause();
                player.pause();
                break;
            case 'seek':
                // Só busca se a diferença for significativa (evita micro-ajustes)
                if (Math.abs(player.currentTime - data.time) > 1.5) {
                    player.currentTime = data.time;
                }
                // Sincroniza o tempo da dublagem aplicando o atraso definido pelo usuário
                dubPlayer.currentTime = player.currentTime + parseFloat(dubDelayInput.value);
                break;
        }
    } catch (e) {
        console.error("Erro ao sincronizar player:", e);
    }

    // Desativa a flag após um tempo
    setTimeout(() => { isSyncing = false; }, 500);
});

// Evento para corrigir o tempo do cliente caso ele saia de sincronia
socket.on('force_sync', (data) => {
    if (isHost || isSyncing) return;

    // Calcula a latência (ping) da requisição
    const ping = Date.now() - syncRequestTime;
    const latency = ping / 2; // Tempo de ida
    const correctedTime = data.time + (latency / 1000); // Converte latência para segundos

    console.log(`Sync forçado recebido. Tempo do Host: ${data.time.toFixed(2)}s, Ping: ${ping}ms, Tempo Corrigido: ${correctedTime.toFixed(2)}s`);
    statusIndicator.innerHTML = `Ping: <span class="ping-value">${ping} ms</span>`;

    // Só ajusta se a diferença for maior que 2 segundos para evitar "pulos"
    if (Math.abs(player.currentTime - correctedTime) > 2) {
        console.log(`Corrigindo tempo do vídeo de ${player.currentTime.toFixed(2)}s para ${correctedTime.toFixed(2)}s.`);
        isSyncing = true;
        player.currentTime = correctedTime;
        // Garante que o estado de play/pause também seja sincronizado
        if (data.paused && !player.paused) {
            player.pause();
        } else if (!data.paused && player.paused) {
            player.play();
        }
        setTimeout(() => { isSyncing = false; }, 500);
    }
});

// --- Eventos Específicos do Host ---

// O servidor pede o estado atual do host para sincronizar outro cliente
socket.on('get_host_time', (callback) => {
    if (isHost) {
        callback({
            time: player.currentTime,
            paused: player.paused
        });
    }
});


// --- Listeners de Eventos do Player ---

player.on('play', () => {
    if (isHost && !isSyncing) {
        console.log("Host deu Play");
        if (!player.muted) dubPlayer.pause(); else dubPlayer.play();
        socket.emit('host_sync', { type: 'play', time: player.currentTime });
        return;
    }

    if (!isHost) {
        if (syncInterval) clearInterval(syncInterval);
        syncInterval = setInterval(() => {
            // Só pede o sync se o vídeo estiver de fato tocando (não pausado)
            if (!player.paused) {
                console.log("Cliente pedindo sync de tempo...");
                syncRequestTime = Date.now(); // Guarda o tempo do envio
                socket.emit('request_sync');
            }
        }, 3000); // A cada 3 segundos
    }
});

player.on('pause', () => {
    if (isHost && !isSyncing) {
        console.log("Host deu Pause");
        dubPlayer.pause();
        socket.emit('host_sync', { type: 'pause', time: player.currentTime });
        return;
    }

    // Se não for o host, para o intervalo de sincronização ao pausar
    if (!isHost) {
        if (syncInterval) {
            clearInterval(syncInterval);
            syncInterval = null;
        }
    }
});

player.on('seeked', () => {
    if (isHost && !isSyncing) {
        console.log("Host buscou (Seek)");
        dubPlayer.currentTime = player.currentTime + parseFloat(dubDelayInput.value);
        socket.emit('host_sync', { type: 'seek', time: player.currentTime });
    }
});
