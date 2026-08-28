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

O diretório deve existir e ser legível. IDs precisam ser únicos e podem conter letras, números, ponto, hífen e sublinhado. Mudanças exigem reiniciar o processo. Tipos de Source são plugins descobertos em `src/media_sources/plugins`; consulte `docs/media-source-plugins.md`.

3. Execute `python src/main.py` e abra `http://localhost:5467/host`.

O playback usa um manifesto MPEG-DASH local e Shaka Player 5.2.0 hospedado pelo próprio
WatchParty. A origem `directory` cria derivados quando FFmpeg/FFprobe estão disponíveis; sem
eles, o catálogo continua navegável e anuncia playback indisponível.

Para uma origem privada `crunchyroll`, habilite o exemplo de `save.example.json`, informe o
cookie `etp_rt` somente em `save.json` e mantenha `worker_path` como
`bin\\crunchyroll-worker.exe`. Para seu dispositivo Widevine, configure simultaneamente
`client_id_path` e `private_key_path`; alternativamente, configure somente
`widevine_device_path` para um arquivo `.wvd`. Instruções de build e segurança ficam em
`tools/crunchyroll-worker/README.md`. Esses arquivos são segredos locais e estão ignorados
pelo Git; tokens, URLs de playback, licenças e chaves nunca são persistidos pelo processo Python.

O plugin Crunchyroll mantém seu próprio índice em `<cache_path>/.crunchyroll/cache.sqlite3`.
No painel do host é possível inspecionar cobertura, escolher qualidade/áudios/legendas, iniciar
download, adicionar ASS/SRT/VTT, limpar grupos de segmentos e executar `Salvar como MP4`.
MP4 nunca é criado automaticamente; jobs continuam ao fechar o navegador, mas não sobrevivem
ao reinício do servidor.

Vídeos aceitos: MP4, MKV, WebM e AVI. Sidecars ficam junto ao vídeo nas convenções `.subs/<nome>.<idioma>.vtt` e `.dubs/<nome>.<idioma>.mp3|aac|ogg`. Imagens usam `.previews/<nome>_poster.png`, `.previews/<nome>_thumbnail.png`, `.previews/poster.png` e `.previews/thumbnail.png`; os nomes antigos com `banner.png` continuam aceitos para compatibilidade.

## Docker e TURN

Copie `.env.example` para `.env`. O Compose monta `WATCHPARTY_MEDIA_DIR` em `/media` com leitura e escrita para `.previews` e `.watchparty`, e usa `docker/save.json` gravável para persistir o toggle administrativo. Para várias origens, adicione mounts graváveis e os respectivos caminhos internos ao arquivo JSON.

Execute `docker compose up -d --build`. Configure `TURN_HOST` e um `TURN_SECRET` longo; publique as portas TURN indicadas no Compose. O modo WebRTC pode ser alterado no painel do host.

## Banners administrativos

O plugin `directory` pode escrever pôsteres e thumbnails diretamente em `.previews` pelo painel.
Como alternativa administrativa em lote, use:

```bash
python make_banners.py
python make_banners.py --source-id filmes
```

O script processa apenas origens `directory` habilitadas, continua após falhas e apresenta um resumo.
