
export async function initializeChat(socket, currentUserName, showNotification) {
    // 1. Carrega o HTML do chat no container
    const chatContainer = document.getElementById('chat-container');
    if (!chatContainer) {
     console.error('Elemento #chat-container não encontrado. O chat não pode ser inicializado.');
     return;
    }
    try {
     const response = await fetch('chat/chat.html');
     chatContainer.innerHTML = await response.text();
    } catch (error) {
     console.error('Falha ao carregar o HTML do chat:', error);
     return;
    }

    // 2. Pega as referências dos elementos do DOM após o carregamento
    const sidebar = document.getElementById('sidebar');
    const toggleBtn = document.getElementById('sidebar-toggle');
    const chatBox = document.getElementById('chat-box');
    const chatInput = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');
    const userList = document.getElementById('user-list');

    // 3. Lógica do Módulo

    // --- Funções de Chat ---
    function sendMessage(text) {
     const message = text || chatInput.value;
     if (message.trim()) {
         socket.emit('send_message', message);
         chatInput.value = '';
     }
    }

    function addChatMessage(data) {
     // data = { sender, pfp, text }
     const msg = document.createElement('p');
     msg.classList.add('chat-msg');

     let pfpImg = '';
     if (data.pfp) {
         pfpImg = `<img src="${data.pfp}" alt="pfp">`;
     }

     msg.innerHTML = `${pfpImg}<strong>${data.sender}:</strong> ${data.text}`;
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

         if (!response.ok) throw new Error(`Upload failed: ${response.status}`);

         const image = await response.json();
         if (!image || !image.url) throw new Error('Resposta inválida do servidor');

         const imgTag = `<img src="${image.url}" style="width:100%;height:100%;object-fit:cover;display:block; border-radius: 1rem;">`;
         sendMessage(imgTag);
     } catch (error) {
         console.error('Erro ao enviar imagem:', error);
         addChatMessage({ sender: 'System', text: 'Erro ao enviar imagem.' });
     }
    }

    // --- Listeners de Eventos do DOM ---
    sendBtn.onclick = () => sendMessage();
    chatInput.onkeydown = (e) => { if (e.key === 'Enter') sendMessage(); };

    chatInput.addEventListener('paste', (e) => {
     const items = (e.clipboardData || e.originalEvent.clipboardData).items;
     for (const item of items) {
         if (item.type.indexOf('image') !== -1) {
             e.preventDefault();
             handleImageUpload(item.getAsFile());
         }
     }
    });

    chatInput.addEventListener('dragover', (e) => e.preventDefault());
    chatInput.addEventListener('drop', (e) => {
     e.preventDefault();
     const file = e.dataTransfer?.files[0];
     if (file && file.type.startsWith('image/')) {
         handleImageUpload(file);
     }
    });

    // --- Lógica da Sidebar ---
    function toggleSidebar() {
     sidebar.classList.toggle('collapsed');
     if (sidebar.classList.contains('collapsed')) {
         toggleBtn.innerHTML = '<';
         toggleBtn.title = 'Expandir chat';
         chatContainer.style.width = '0';
     } else {
         toggleBtn.innerHTML = '>';
         toggleBtn.title = 'Recolher chat';
         chatContainer.style.width = 'auto';
     }
    }
    toggleBtn.addEventListener('click', toggleSidebar);
    document.addEventListener('keydown', (e) => {
     if (e.key === 'Tab' && !e.shiftKey && document.activeElement.tagName !== 'INPUT') {
         e.preventDefault();
         toggleSidebar();
     }
    });

    // --- Listeners de Eventos do Socket.IO ---
    socket.on('update_users', (users) => {
     userList.innerHTML = '';
     for (const sid in users) {
         const user = users[sid];
         const li = document.createElement('div');
         li.classList.add('user-item');
         const pfpImg = user.pfp ? `<img src="${user.pfp}" alt="pfp">` : '';
         const hostBadge = user.isHost ? '<span id="host-badge">HOST</span>' : '';
         li.innerHTML = `${pfpImg} ${user.name} ${hostBadge}`;
         userList.appendChild(li);
     }
    });

    socket.on('new_message', (data) => {
     if (data.sender !== currentUserName) {
         showNotification(`<strong>${data.sender}</strong>: ${data.text.length > 50 ? data.text.substring(0, 50) + '...' : data.text}`);
     }
     addChatMessage(data);
    });

    console.log('Módulo de Chat inicializado.');
}