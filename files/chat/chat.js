
export async function initializeChat(socket, currentUserName, showNotification, getIsHost) {
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
    
    const contextMenu = document.getElementById('user-context-menu');
    const transferHostBtn = document.getElementById('transfer-host-btn');
    const directConnectBtn = document.getElementById('direct-connect-btn');
    const togglePeerMuteBtn = document.getElementById('toggle-peer-mute-btn');

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
         pfpImg = `<img src="${data.pfp}" alt="pfp" class="user-pfp">`;
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

    // --- Lógica do Menu de Contexto do Usuário ---
    let selectedUserSid = null;
    
    function showUserContextMenu(e, sid, user) {
        if (sid === socket.id) return; // Não mostrar para si mesmo
        
        selectedUserSid = sid;
        
        if (getIsHost && getIsHost()) {
            transferHostBtn.style.display = 'block';
        } else {
            transferHostBtn.style.display = 'none';
        }
        
        // Lógica para botões de WebRTC
        const userItem = e.currentTarget;
        if (userItem.classList.contains('peer-connected')) {
            directConnectBtn.style.display = 'none';
            togglePeerMuteBtn.style.display = 'block';
            const isMuted = userItem.classList.contains('peer-muted');
            togglePeerMuteBtn.textContent = isMuted ? 'Desmutar Áudio' : 'Mutar Áudio';
        } else {
            directConnectBtn.style.display = 'block';
            togglePeerMuteBtn.style.display = 'none';
        }

        
        contextMenu.style.display = 'flex';
        
        const sidebarRect = sidebar.getBoundingClientRect();
        let top = e.clientY - sidebarRect.top;
        let left = e.clientX - sidebarRect.left;
        
        contextMenu.style.top = `${top}px`;
        contextMenu.style.left = `${left}px`;
        
        // Ajuste caso o menu acabe saindo da área delimitada da sidebar
        setTimeout(() => {
            const menuRect = contextMenu.getBoundingClientRect();
            if (menuRect.right > sidebarRect.right) {
                contextMenu.style.left = `${left - menuRect.width}px`;
            }
            if (menuRect.bottom > sidebarRect.bottom) {
                contextMenu.style.top = `${top - menuRect.height}px`;
            }
        }, 0);
    }
    
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.user-item') && !e.target.closest('#user-context-menu')) {
            contextMenu.style.display = 'none';
        }
    });
    
    transferHostBtn.addEventListener('click', () => {
        if (selectedUserSid) {
            socket.emit('transfer_host', selectedUserSid);
            contextMenu.style.display = 'none';
        }
    });
    
    directConnectBtn.addEventListener('click', () => {
        if (selectedUserSid) {
            socket.emit('webrtc_signal', {
                target_sid: selectedUserSid,
                payload: { type: 'request', from_name: currentUserName }
            });
            showNotification(`Pedido de conexão direta enviado.`, 'info');
            contextMenu.style.display = 'none';
        }
    });

    togglePeerMuteBtn.addEventListener('click', () => {
        if (selectedUserSid) {
            document.dispatchEvent(new CustomEvent('togglePeerMute', { detail: { sid: selectedUserSid } }));
            contextMenu.style.display = 'none';
        }
    });

    // --- Listeners de Eventos do Socket.IO ---
    socket.on('update_users', (users) => {
     userList.innerHTML = '';
     for (const sid in users) {
         const user = users[sid];
         const li = document.createElement('div');
         li.classList.add('user-item');
         if (user.isHost) {
             li.classList.add('chat-host');
         }
         const pfpImg = user.pfp ? `<img src="${user.pfp}" alt="pfp" class="user-pfp">` : '';
         li.innerHTML = `${pfpImg} ${user.name}`;
         li.dataset.sid = sid; // Adiciona SID para manipulação externa (WebRTC UI)
         
         li.addEventListener('click', (e) => {
             showUserContextMenu(e, sid, user);
         });
         
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