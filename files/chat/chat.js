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
    const pingDisplay = document.getElementById('peer-ping-display');

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
     const isMobile = window.matchMedia('(max-width: 900px)').matches;
     sidebar.classList.toggle('collapsed');
     if (sidebar.classList.contains('collapsed')) {
         toggleBtn.innerHTML = '<';
         toggleBtn.title = 'Expandir chat';
         chatContainer.style.width = isMobile ? '100%' : '0';
         chatContainer.style.flexBasis = isMobile ? '48px' : '';
     } else {
         toggleBtn.innerHTML = '>';
         toggleBtn.title = 'Recolher chat';
         chatContainer.style.width = isMobile ? '100%' : 'auto';
         chatContainer.style.flexBasis = '';
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
            pingDisplay.style.display = 'block';
            pingDisplay.innerHTML = 'Ping: Calculando...';
            document.dispatchEvent(new CustomEvent('requestPeerPing', { detail: { sid: sid } }));
        } else {
            directConnectBtn.style.display = 'block';
            pingDisplay.style.display = 'none';
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

    document.addEventListener('receivePeerPing', (e) => {
        if (selectedUserSid === e.detail.sid && pingDisplay && pingDisplay.style.display === 'block') {
            const stats = e.detail.stats;
            if (stats) {
                const pingText = stats.ping !== null ? `${Math.round(stats.ping)} ms` : '-- ms';
                const typeMap = {
                    'host': 'Local (LAN)',
                    'srflx': 'STUN (Pública)',
                    'prflx': 'P2P (Reflexiva)',
                    'relay': 'TURN (Relay)'
                };
                const lType = typeMap[stats.localType] || stats.localType;
                const rType = typeMap[stats.remoteType] || stats.remoteType;

                // Exibimos a versão do IP (IPv4 ou IPv6) ao lado da rota
                const lIpVer = stats.localIpVersion || 'Unknown';
                const rIpVer = stats.remoteIpVersion || 'Unknown';

                pingDisplay.innerHTML = `
                    <div><strong>Ping:</strong> ${pingText}</div>
                    <div style="font-size: 0.85em; margin-top: 6px; opacity: 0.85; line-height: 1.4;">
                        <strong>Rota:</strong> ${lType} (${lIpVer}) &harr; ${rType} (${rIpVer})<br>
                        <strong>Proto:</strong> ${stats.protocol ? stats.protocol.toUpperCase() : '--'}
                    </div>
                `;
            } else {
                pingDisplay.innerHTML = 'Estatísticas Indisponíveis';
            }
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

         // Restaura classes WebRTC se a conexão já existe
         const existingAudio = document.getElementById(`peer-audio-${sid}`);
         if (existingAudio) {
             li.classList.add('peer-connected');
             if (existingAudio.muted) li.classList.add('peer-muted');
         }

         const pfpImg = user.pfp ? `<img src="${user.pfp}" alt="pfp" class="user-pfp">` : '';
         li.innerHTML = `${pfpImg} <span class="user-name">${user.name}</span>`;
         li.dataset.sid = sid; // Adiciona SID para manipulação externa (WebRTC UI)
         
         if (sid !== socket.id) {
             const muteBtn = document.createElement('button');
             muteBtn.className = 'peer-mute-btn';
             if (existingAudio && existingAudio.muted) muteBtn.classList.add('muted');
             muteBtn.title = "Mutar Áudio";
             muteBtn.innerHTML = `
                 <svg class="mic-on" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"></path><path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.8 6.47 6 6.92V21h2v-3.08c3.2-.45 6-3.39 6-6.92h-2z"></path></svg>
                 <svg class="mic-off" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path d="M19 11h-1.7c0 .74-.16 1.43-.43 2.05l1.23 1.23c.56-.98.9-2.09.9-3.28zm-4.02.17c0-.06.02-.11.02-.17V5c0-1.66-1.34-3-3-3S9 3.34 9 5v.18l5.98 5.99zM4.27 3L3 4.27l6.01 6.01V11c0 1.66 1.34 3 3 3 .23 0 .44-.03.65-.08l1.66 1.66c-.71.33-1.5.52-2.31.52-2.76 0-5-2.24-5-5H5c0 3.53 2.8 6.47 6 6.92V21h2v-3.08c.91-.13 1.77-.45 2.54-.9L19.73 21 21 19.73 4.27 3z"></path></svg>
             `;
             muteBtn.onclick = (e) => {
                 e.stopPropagation();
                 document.dispatchEvent(new CustomEvent('togglePeerMute', { detail: { sid: sid } }));
             };
             li.appendChild(muteBtn);
         }

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
