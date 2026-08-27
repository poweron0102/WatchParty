# Watch Party

Aplicação Python para assistir a vídeos sincronizados com amigos. Os catálogos são origens independentes e somente leitura.

## Instalação local

1. Instale as dependências com `pip install -r requirements.txt`.
2. Copie `save.example.json` para `save.json` e configure uma ou mais origens:

```json
{
  "port": 5467,
  "use_cloudflare": false,
  "sources": [
    {
      "id": "filmes",
      "type": "directory",
      "label": "Filmes",
      "enabled": true,
      "options": { "path": "D:/Filmes" }
    }
  ]
}
```

O diretório deve existir e ser legível. IDs precisam ser únicos e podem conter letras, números, ponto, hífen e sublinhado. Mudanças exigem reiniciar o processo.

3. Execute `python src/main.py` e abra `http://localhost:5467/host`.

Vídeos aceitos: MP4, MKV, WebM e AVI. Sidecars ficam junto ao vídeo nas convenções `.subs/<nome>.<idioma>.vtt`, `.dubs/<nome>.<idioma>.mp3|aac|ogg` e `.previews/<nome>_banner.png`. Coleções podem usar `.previews/banner.png`.

## Docker e TURN

Copie `.env.example` para `.env`. O Compose monta `WATCHPARTY_MEDIA_DIR` em `/media`, somente para leitura, e usa `docker/save.json`. Para várias origens, adicione mounts somente leitura ao Compose e os respectivos caminhos internos ao arquivo JSON.

Execute `docker compose up -d --build`. Configure `TURN_HOST` e um `TURN_SECRET` longo; publique as portas TURN indicadas no Compose. O modo WebRTC pode ser alterado no painel do host.

## Banners administrativos

O servidor nunca escreve nas origens. Gere thumbnails explicitamente com:

```bash
python make_banners.py
python make_banners.py --source-id filmes
```

O script processa apenas origens `directory` habilitadas, continua após falhas e apresenta um resumo.
