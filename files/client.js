// /files/client.js

// --- Conexão e Elementos DOM ---
const socket = io();

const video = document.getElementById('player');
const chatBox = document.getElementById('chat-box');
const chatInput = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');
const userList = document.getElementById('user-list');
const pingInfo = document.createElement('div'); // Criei o elemento para o ping
pingInfo.id = 'ping-info';
userList.parentNode.insertBefore(pingInfo, userList); // Adicionei antes da lista de usuários

// --- Estado do Cliente ---
let isHost = false;
let isSyncing = false; // Flag para evitar loops de eventos (muito importante!)
let syncInterval = null; // Nosso intervalo de sincronização
let syncRequestTime = 0; // Para calcular o ping

// --- Pega dados do "Login" ---
const userName = sessionStorage.getItem('userName');
const userPfp = sessionStorage.getItem('userPfp');

// Se não tiver nome, volta para a página inicial
if (!userName) {
    window.location.href = '/';
}

// --- Envia evento de "Entrar na Sala" ---
socket.emit('join_room', { name: userName, pfp: userPfp });

// --- Funções de Chat ---
function sendMessage() {
    const text = chatInput.value;
    if (text.trim()) {
        socket.emit('send_message', text);
        chatInput.value = '';
    }
}
sendBtn.onclick = sendMessage;
chatInput.onkeydown = (e) => {
    if (e.key === 'Enter') sendMessage();
};

function addChatMessage(data) {
    // data = { sender, pfp, text }
    const msg = document.createElement('p');
    msg.classList.add('chat-msg');

    let pfpImg = '';
    if (data.pfp) {
        pfpImg = `<img src="${data.pfp}" alt="pfp">`;
    }

    msg.innerHTML = `${pfpImg}<strong>${data.sender}:</strong> ${data.text}`; // Cuidado com XSS em produção
    chatBox.appendChild(msg);
    chatBox.scrollTop = chatBox.scrollHeight;
}

// --- Listeners de Eventos do Socket.IO ---

socket.on('set_host', () => {
    isHost = true;
    console.log("Você foi definido como o HOST!");
    // O host é o único que deve ter os controles habilitados
    // (embora 'controls' já esteja lá, isso é conceitual)
});

socket.on('update_users', (users) => {
    userList.innerHTML = '';
    for (const sid in users) {
        const user = users[sid];
        const li = document.createElement('div');
        li.classList.add('user-item');

        let pfpImg = '';
        if (user.pfp) {
            pfpImg = `<img src="${user.pfp}" alt="pfp">`;
        }

        let hostBadge = '';
        if (user.isHost) {
            hostBadge = '<strong>[HOST]</strong>';
        }

        li.innerHTML = `${pfpImg} ${user.name} ${hostBadge}`;
        userList.appendChild(li);
    }
});

socket.on('new_message', (data) => {
    addChatMessage(data);
});

socket.on('sync_state', (state) => {
    console.log({state});
    if (state.video) {
        console.log(`Sincronizando com estado: ${state.video} @ ${state.time}s`);
        isSyncing = true;
        video.src = `/video/${state.video}`;
        video.currentTime = state.time;
        if (state.paused) {
            video.pause();
        } else {
            video.play();
        }
        // Desativa a flag após um tempo para permitir o player "assentar"
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
                video.src = `/video/${data.video}`;
                video.pause();
                video.currentTime = 0;
                break;
            case 'play':
                video.play();
                break;
            case 'pause':
                video.pause();
                break;
            case 'seek':
                // Só busca se a diferença for significativa (evita micro-ajustes)
                if (Math.abs(video.currentTime - data.time) > 1.5) {
                    video.currentTime = data.time;
                }
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
    pingInfo.textContent = `Ping: ${ping}ms`; // Mostra o ping na tela
    const latency = ping / 2; // Tempo de ida
    const correctedTime = data.time + (latency / 1000); // Converte latência para segundos

    console.log(`Sync forçado recebido. Tempo do Host: ${data.time.toFixed(2)}s, Ping: ${ping}ms, Tempo Corrigido: ${correctedTime.toFixed(2)}s`);

    // Só ajusta se a diferença for maior que 2 segundos para evitar "pulos"
    if (Math.abs(video.currentTime - correctedTime) > 2) {
        console.log(`Corrigindo tempo do vídeo de ${video.currentTime.toFixed(2)}s para ${correctedTime.toFixed(2)}s.`);
        isSyncing = true;
        video.currentTime = correctedTime;
        // Garante que o estado de play/pause também seja sincronizado
        if (data.paused && !video.paused) {
            video.pause();
        } else if (!data.paused && video.paused) {
            video.play();
        }
        setTimeout(() => { isSyncing = false; }, 500);
    }
});

// --- Eventos Específicos do Host ---

// O servidor pede o estado atual do host para sincronizar outro cliente
socket.on('get_host_time', (callback) => {
    if (isHost) {
        callback({
            time: video.currentTime,
            paused: video.paused
        });
    }
});


// --- Listeners de Eventos do Player ---

video.onplay = () => {
    if (isHost && !isSyncing) {
        console.log("Host deu Play");
        socket.emit('host_sync', { type: 'play', time: video.currentTime });
        return;
    }

    if (!isHost) {
        if (syncInterval) clearInterval(syncInterval);
        syncInterval = setInterval(() => {
            // Só pede o sync se o vídeo estiver de fato tocando
            if (!video.paused) {
                console.log("Cliente pedindo sync de tempo...");
                syncRequestTime = Date.now(); // Guarda o tempo do envio
                socket.emit('request_sync');
            }
        }, 3000); // A cada 3 segundos
    }
};

video.onpause = () => {
    if (isHost && !isSyncing) {
        console.log("Host deu Pause");
        socket.emit('host_sync', { type: 'pause', time: video.currentTime });
        return;
    }

    // Se não for o host, para o intervalo de sincronização ao pausar
    if (!isHost) {
        if (syncInterval) {
            clearInterval(syncInterval);
            syncInterval = null;
        }
    }
};

video.onseeked = () => {
    if (isHost && !isSyncing) {
        console.log("Host buscou (Seek)");
        socket.emit('host_sync', { type: 'seek', time: video.currentTime });
    }
};
