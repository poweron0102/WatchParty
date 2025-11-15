const socket = io();

// --- Elementos do DOM ---
const inviteLinkField = document.getElementById('invite-link-field');
const copyLinkBtn = document.getElementById('copy-link-btn');
const updateBannersBtn = document.getElementById('update-banners-btn');
const folderGrid = document.getElementById('folder-grid');
const videoGrid = document.getElementById('video-grid');
const videoUrlField = document.getElementById('video-url-field');
const setUrlBtn = document.getElementById('set-url-btn');
const breadcrumbsContainer = document.getElementById('breadcrumbs-container');
const statusMessage = document.getElementById('status-message');

// --- Estado ---
let currentPath = '';
let statusTimeout;

function max(a, b) {
    if (a > b) return a;
    return b;
}

// 1. Buscar o IP/Link do servidor
fetch('/api/get_ip')
    .then(res => res.json())
    .then(data => {
        inviteLinkField.value = data.link;
    });

// 2. Copiar link
copyLinkBtn.onclick = () => {
    inviteLinkField.select();
    document.execCommand('copy'); // Fallback para compatibilidade

    navigator.clipboard.writeText(inviteLinkField.value).then(() => {
        const originalText = copyLinkBtn.querySelector('span').textContent;
        copyLinkBtn.querySelector('span').textContent = 'Copiado!';
        setTimeout(() => {
            copyLinkBtn.querySelector('span').textContent = originalText;
        }, 2000);
    });
};

// 3. Definir vídeo por URL
setUrlBtn.onclick = () => {
    const url = videoUrlField.value.trim();
    if (url) {
        socket.emit('host_set_video', url);
        showStatus(`Vídeo da URL definido!`, 'success');
        videoUrlField.value = '';
    }
};

// 4. Atualizar Banners
updateBannersBtn.onclick = () => {
    const btnText = document.getElementById('update-banners-btn-text');
    const updateIcon = document.getElementById('update-icon');
    const spinnerIcon = document.getElementById('update-spinner');

    btnText.textContent = 'Atualizando...';
    updateBannersBtn.disabled = true;
    updateIcon.classList.add('hidden');
    spinnerIcon.classList.remove('hidden');

    fetch('/api/update_banners', { method: 'POST' })
        .then(res => res.json())
        .then(data => {
            showStatus(data.message || 'Banners atualizados.', 'success');
            navigate(currentPath); // Recarrega a visualização atual
        })
        .catch(() => showStatus('Erro ao atualizar banners.', 'error'))
        .finally(() => {
            btnText.textContent = 'Atualizar Banners';
            updateBannersBtn.disabled = false;
            updateIcon.classList.remove('hidden');
            spinnerIcon.classList.add('hidden');
        });
};

// 5. Navegação de arquivos
function navigate(path = '') {
    currentPath = path;
    fetch(`/api/get_videos?path=${encodeURIComponent(path)}`)
        .then(res => res.json())
        .then(data => {
            renderBreadcrumb(path);
            folderGrid.innerHTML = '';
            videoGrid.innerHTML = '';

            const folders = data.items.filter(item => item.type === 'folder');
            const videos = data.items.filter(item => item.type === 'video');

            if (folders.length > 0) {
                folders.forEach(item => {
                    const itemEl = createItemElement(item);
                    folderGrid.appendChild(itemEl);
                });
            } else {
                folderGrid.innerHTML = '<p class="col-span-full text-center text-gray-500">Nenhuma pasta encontrada.</p>';
            }

            if (videos.length > 0) {
                videos.forEach(item => {
                    const itemEl = createItemElement(item);
                    videoGrid.appendChild(itemEl);
                });
            } else {
                videoGrid.innerHTML = '<p class="col-span-full text-center text-gray-500">Nenhum vídeo encontrado.</p>';
            }

            // Renderiza vídeos
            videos.forEach(item => {
                const itemEl = createItemElement(item);
                mediaGrid.appendChild(itemEl);
            });
        });
}

function createItemElement(item) {
    const itemEl = document.createElement('div');
    itemEl.title = item.name; // Adiciona o nome completo como um tooltip nativo do navegador
    itemEl.className = `media-item ${item.type}`; // Adiciona 'folder' ou 'video' como classe
    itemEl.onclick = () => {
        if (item.type === 'folder') {
            navigate(item.path);
        } else if (item.type === 'video') {
            setVideo(item.path);
        }
    };

    // Adiciona o indicador de tipo (pasta ou vídeo)
    const typeIndicator = document.createElement('div');
    typeIndicator.className = 'type-indicator';
    const typeIcon = document.createElement('span');
    if (item.type === 'folder') {
        typeIcon.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor"><path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" /></svg>`;
    } else {
        typeIcon.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-2a1 1 0 000-1.664l-3-2z" clip-rule="evenodd" /></svg>`;
    }
    typeIndicator.appendChild(typeIcon);
    itemEl.appendChild(typeIndicator);

    const nameEl = document.createElement('div');
    nameEl.className = 'file-name';
    nameEl.textContent = item.name;

    const banner = document.createElement('img');
    banner.className = 'banner';
    banner.alt = item.name;

    const defaultFolderBanner = '/banner_folder.png';
    const defaultVideoBanner = '/banner_video.png';

    // Função para buscar banner via scraping no backend
    const fetchBannerFromBackend = () => {
        // Remove o ano do título (ex: "Filme (2023)") para melhorar a busca
        const searchTerm = item.name.replace(/\s*\(\d{4}\)\s*$/, '').trim();

        fetch(`/api/scrape_banner?title=${encodeURIComponent(searchTerm)}`)
            .then(res => res.json())
            .then(data => {
                if (data.imageUrl) {
                    banner.src = data.imageUrl;
                } else {
                    console.log(`Banner para "${item.name}" não encontrado. Usando banner padrão.`);
                    banner.src = item.type === 'folder' ? defaultFolderBanner : defaultVideoBanner;
                }
            })
            .catch(error => {
                console.error('Erro ao buscar banner via backend:', error);
                banner.src = item.type === 'folder' ? defaultFolderBanner : defaultVideoBanner;
            });
    };

    if (item.type === 'folder') {
        // O backend salva em: /path/to/folder/.previews/banner.png
        banner.src = `/videos/${item.path}/.previews/banner.png?t=${new Date().getTime()}`;
        banner.onerror = fetchBannerFromBackend;
    } else if (item.type === 'video') {
        const lastSlashIndex = max(item.path.lastIndexOf('/'), item.path.lastIndexOf('\\'));
        const dirPath = lastSlashIndex === -1 ? '' : item.path.substring(0, lastSlashIndex);
        const baseName = item.name.substring(0, item.name.lastIndexOf('.'));

        banner.src = `/videos/${dirPath ? dirPath + '/' : ''}.previews/${baseName}_banner.png?t=${new Date().getTime()}`;
        banner.onerror = fetchBannerFromBackend;
    }
    itemEl.appendChild(banner);
    itemEl.appendChild(nameEl);
    return itemEl;
}

function renderBreadcrumb(path) {
    breadcrumbsContainer.innerHTML = '';
    const parts = path.split('/').filter(p => p);
    
    // Link para o Início (Raiz)
    const rootLi = document.createElement('li');
    const rootLink = document.createElement('a');
    rootLink.href = '#';
    rootLink.textContent = 'Início';
    rootLink.className = 'brand hover:underline';
    rootLink.onclick = (e) => { e.preventDefault(); navigate(''); };
    rootLi.appendChild(rootLink);
    breadcrumbsContainer.appendChild(rootLi);

    let currentPath = '';
    parts.forEach((part, index) => {
        // Adiciona o separador
        const separator = document.createElement('li');
        separator.textContent = '>';
        separator.className = 'text-gray-500 mx-1';
        breadcrumbsContainer.appendChild(separator);

        currentPath = `${currentPath}${part}/`;
        const partLi = document.createElement('li');

        if (index === parts.length - 1) {
            // Última parte não é clicável
            const span = document.createElement('span');
            span.textContent = part;            
            span.className = 'font-medium';
            span.style.color = 'var(--text-primary)';
            partLi.appendChild(span);
        } else {
            const link = document.createElement('a');
            link.href = '#';
            link.textContent = part;
            link.className = 'brand hover:underline';
            const capturedPath = currentPath;
            link.onclick = (e) => { e.preventDefault(); navigate(capturedPath); };
            partLi.appendChild(link);
        }
        breadcrumbsContainer.appendChild(partLi);
    });
}

function setVideo(videoPath) {
    socket.emit('host_set_video', videoPath);
    const fileName = videoPath.split('/').pop();
    showStatus(`Vídeo "${fileName}" definido para todos!`, 'success');
}

// Iniciar a navegação na raiz
navigate();
