document.getElementById('login-form').onsubmit = async (e) => {
    e.preventDefault();

    const name = document.getElementById('name').value;
    const pfpFile = document.getElementById('pfp').files[0];
    let pfpUrl = '';

    if (pfpFile) {
        // 1. Faz upload da foto para o cache
        const formData = new FormData();
        formData.append('file', pfpFile);

        try {
            const res = await fetch('/api/upload_image', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();
            pfpUrl = data.url; // Deverá ser algo como "/cache/foto.png"
        } catch (err) {
            console.error("Falha no upload da foto", err);
        }
    }

    // 2. Salva no sessionStorage para usar na próxima página
    sessionStorage.setItem('userName', name);
    sessionStorage.setItem('userPfp', pfpUrl);

    // 3. Redireciona para a sala
    window.location.href = '/party';
};