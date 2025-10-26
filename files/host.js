const socket = io();

const linkEl = document.getElementById('access-link');
const copyLinkBtn = document.getElementById('copy-link-btn');
const updateBannersBtn = document.getElementById('update-banners-btn');
const fileBrowser = document.getElementById('file-browser');
const breadcrumb = document.getElementById('breadcrumb');

let currentPath = '';

// 1. Buscar o IP/Link do servidor
fetch('/api/get_ip')
    .then(res => res.json())
    .then(data => {
        linkEl.textContent = data.link;
    });

// 2. Copiar link
copyLinkBtn.onclick = () => {
    navigator.clipboard.writeText(linkEl.textContent).then(() => {
        copyLinkBtn.textContent = 'Copiado!';
        setTimeout(() => { copyLinkBtn.textContent = 'Copiar Link'; }, 2000);
    });
};

// 3. Atualizar Banners
updateBannersBtn.onclick = () => {
    updateBannersBtn.textContent = 'Atualizando...';
    updateBannersBtn.disabled = true;

    fetch('/api/update_banners', { method: 'POST' })
        .then(res => res.json())
        .then(data => {
            alert(data.message);
            navigate(currentPath); // Recarrega a visualização atual
        })
        .finally(() => {
            updateBannersBtn.textContent = 'Atualizar Banners';
            updateBannersBtn.disabled = false;
        });
};

// 4. Navegação de arquivos
function navigate(path = '') {
    currentPath = path;
    fetch(`/api/get_videos?path=${encodeURIComponent(path)}`)
        .then(res => res.json())
        .then(data => {
            renderBreadcrumb(path);
            fileBrowser.innerHTML = ''; // Limpa todo o conteúdo

            if (data.items.length === 0) {
                fileBrowser.innerHTML = '<p>Nenhum item encontrado.</p>';
                return;
            }

            const folders = data.items.filter(item => item.type === 'folder');
            const videos = data.items.filter(item => item.type === 'video');

            // Renderiza pastas primeiro
            folders.forEach(item => {
                const itemEl = createItemElement(item);
                fileBrowser.appendChild(itemEl);
            });

            data.items.forEach(item => {
                const itemEl = document.createElement('div');
                itemEl.className = 'file-item';
                itemEl.onclick = () => {
                    if (item.type === 'folder') {
                        navigate(item.path);
                    }
                };

                const nameEl = document.createElement('div');
                nameEl.className = 'file-name';
                nameEl.textContent = item.name;

                const banner = document.createElement('img');
                banner.className = 'banner';
                banner.alt = item.name;

                banner.src = `/videos/${item.path}/banner.png?t=${new Date().getTime()}`;
                banner.onerror = () => { banner.src = '/banner_folder.png'; };
                itemEl.appendChild(banner);

                itemEl.appendChild(nameEl);
            });

            // Se houver vídeos, adiciona um título e os renderiza
            if (videos.length > 0) {
                const videosHeader = document.createElement('h3');
                videosHeader.textContent = 'Vídeos';
                videosHeader.style.gridColumn = '1 / -1'; // Ocupa a linha inteira
                fileBrowser.appendChild(videosHeader);

                videos.forEach(item => {
                    const itemEl = createItemElement(item);
                    fileBrowser.appendChild(itemEl);
                });
            }
        });
}

function createItemElement(item) {
    const itemEl = document.createElement('div');
    itemEl.className = 'file-item';
    itemEl.onclick = () => {
        if (item.type === 'folder') {
            navigate(item.path);
        } else if (item.type === 'video') {
            setVideo(item.path);
        }
    };

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
        banner.src = `/videos/${item.path}/banner.png?t=${new Date().getTime()}`;
        banner.onerror = fetchBannerFromBackend;
    } else if (item.type === 'video') {
        const dirPath = item.path.substring(0, item.path.lastIndexOf('/'));
        banner.src = `/videos/${dirPath}/banner.png?t=${new Date().getTime()}`;
        banner.onerror = fetchBannerFromBackend;
    }
    itemEl.appendChild(banner);
    itemEl.appendChild(nameEl);
    return itemEl;
}

function renderBreadcrumb(path) {
    breadcrumb.innerHTML = '';
    const parts = path.split('/').filter(p => p);
    
    const rootLink = document.createElement('a');
    rootLink.href = '#';
    rootLink.textContent = 'Início';
    rootLink.onclick = (e) => {
        e.preventDefault();
        navigate('');
    };
    breadcrumb.appendChild(rootLink);

    let currentPath = '';
    parts.forEach(part => {
        currentPath = `${currentPath}${part}/`;
        const link = document.createElement('a');
        link.href = '#';
        link.textContent = ` > ${part}`;
        const capturedPath = currentPath;
        link.onclick = (e) => {
            e.preventDefault();
            navigate(capturedPath);
        };
        breadcrumb.appendChild(link);
    });
}

function setVideo(videoPath) {
    socket.emit('host_set_video', videoPath);
    alert(`Vídeo "${videoPath}" definido para todos os usuários!`);
}

// Iniciar a navegação na raiz
navigate();
