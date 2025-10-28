// /files/client.js

// --- Conexão e Elementos DOM ---
const socket = io();
// Inicializa o Plyr. Ele substitui o elemento <video> padrão por um mais robusto.
const player = new Plyr('#player', {
    tooltips: { controls: true, seek: true }
});
const video = player.media; // Acesso ao elemento <video> original, se necessário
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


// --- Funções de Chat ---
function sendMessage(text) {
    const message = text || chatInput.value;
    if (message.trim()) {
        socket.emit('send_message', message);
        chatInput.value = '';
    }
}
sendBtn.onclick = () => sendMessage();
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

// --- Upload de Imagem ---
async function handleImageUpload(file) {
    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch('/api/upload_image', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            throw new Error(`Upload failed: ${response.status} ${response.statusText}`);
        }

        const image = await response.json();
        if (!image || !image.url) {
            throw new Error('Resposta inválida do servidor');
        }

        const imgTag = `<img src="${image.url}" style="width:100%;height:100%;object-fit:cover;display:block; border-radius: 1rem;">`;
        sendMessage(imgTag);
    } catch (error) {
        console.error('Erro ao enviar imagem:', error);
        addChatMessage({
            sender: 'System',
            text: 'Erro ao enviar imagem.'
        });
    }
}

chatInput.addEventListener('paste', (e) => {
    const items = (e.clipboardData || e.originalEvent.clipboardData).items;
    for (const item of items) {
        if (item.type.indexOf('image') !== -1) {
            const blob = item.getAsFile();
            handleImageUpload(blob);
            e.preventDefault();
        }
    }
});

chatInput.addEventListener('dragover', (e) => {
    e.preventDefault();
});

chatInput.addEventListener('drop', (e) => {
    e.preventDefault();
    const files = (e.dataTransfer || e.originalEvent.dataTransfer).files;
    if (files.length > 0) {
        const file = files[0];
        if (file.type.indexOf('image') !== -1) {
            handleImageUpload(file).then(r => {});
        }
    }
});


// --- Listeners de Eventos do Socket.IO ---

socket.on('set_host', () => {
    isHost = true;
    console.log("Você foi definido como o HOST!");
    // O host é o único que deve ter os controles habilitados
    // (embora 'controls' já esteja lá, isso é conceitual)
});

socket.on('update_users', (users) => {
    userList.innerHTML = '';
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
        const newHostName = users[newHostSid].name;
        // Não notificar se você se tornou o host (já tem o log no console)
        if (newHostSid !== socket.id) {
            showNotification(`<strong>${newHostName}</strong> agora é o host.`, 'warning');
        }
    }

    clientState.users = users; // Atualiza o estado

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
            hostBadge = '<span id="host-badge">HOST</span>';
        }

        li.innerHTML = `${pfpImg} ${user.name} ${hostBadge}`;
        userList.appendChild(li);
    }
});

socket.on('new_message', (data) => {
    // Mostra notificação apenas para mensagens de outros usuários
    if (data.sender !== userName) {
        showNotification(`<strong>${data.sender}</strong>: ${data.text.length > 50 ? data.text.substring(0, 50) + '...' : data.text}`);
    }
    addChatMessage(data);
});

socket.on('sync_state', (state) => {
    console.log({state});
    if (state.video) {
        console.log(`Sincronizando com estado: ${state.video} @ ${state.time}s`);
        isSyncing = true;
        // Usa a API do Plyr para mudar a fonte do vídeo
        player.source = {
            type: 'video',
            sources: [{ src: `/video/${state.video}` }],
        };
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
                player.source = {
                    type: 'video',
                    sources: [{ src: `/video/${data.video}` }],
                };
                player.pause();
                player.currentTime = 0;
                break;
            case 'play':
                player.play();
                break;
            case 'pause':
                player.pause();
                break;
            case 'seek':
                // Só busca se a diferença for significativa (evita micro-ajustes)
                if (Math.abs(player.currentTime - data.time) > 1.5) {
                    player.currentTime = data.time;
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
        socket.emit('host_sync', { type: 'seek', time: player.currentTime });
    }
});
