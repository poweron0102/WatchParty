// Esta página também se conecta ao socket para enviar o comando
const socket = io();

const linkEl = document.getElementById('access-link');
const videoList = document.getElementById('video-list');
const setVideoBtn = document.getElementById('set-video-btn');

// 1. Buscar o IP/Link do servidor
fetch('/api/get_ip')
    .then(res => res.json())
    .then(data => {
        linkEl.textContent = data.link;
    });

// 2. Buscar a lista de vídeos disponíveis
fetch('/api/get_videos')
    .then(res => res.json())
    .then(data => {
        videoList.innerHTML = '';
        if (data.videos.length === 0) {
             videoList.innerHTML = '<option disabled>Nenhum vídeo encontrado</option>';
             setVideoBtn.disabled = true;
        } else {
            data.videos.forEach(video => {
                const option = document.createElement('option');
                option.value = video;
                option.textContent = video;
                videoList.appendChild(option);
            });
        }
    });

// 3. Enviar comando para trocar o vídeo de todos
setVideoBtn.onclick = () => {
    const selectedVideo = videoList.value;
    if (selectedVideo) {
        // Envia o evento para o servidor
        socket.emit('host_set_video', selectedVideo);
        alert('Vídeo definido para todos os usuários!');
    }
};