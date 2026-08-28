# Plano de implementação: `CrunchyrollSource` com cache read-through segmentado

Status: implementação ativa. A arquitetura de plugins, cache SQLite por instância e fluxo manual de download/exportação substituem as decisões antigas de finalização automática.

## Resultado esperado

Adicionar ao WatchParty uma Source privada para pesquisar e navegar pelo catálogo da Crunchyroll e reproduzir mídia por MPEG-DASH local enquanto os segmentos necessários são baixados, descriptografados, validados e armazenados. O cache é esparso: assistir, buscar uma posição ou selecionar uma faixa materializa somente os intervalos efetivamente demandados pelo player, mais a representação canônica correspondente de vídeo.

Um MP4 só é produzido quando o host executa explicitamente `Salvar como MP4`. O job completa os segmentos selecionados que ainda estiverem ausentes, incorpora os áudios e legendas escolhidos e publica a saída atomicamente no `export_path`. Não existe finalização automática por cobertura ou inatividade.

Toda reprodução audiovisual passa por um `PlaybackModule` central e por um manifesto DASH local. `CrunchyrollSource` e `DirectorySource` são Adapters da mesma Interface interna de origem segmentada; o frontend não conhece as diferenças entre arquivo local, cache parcial, download remoto, DRM, remux ou transcode.

Este plano usa como referência o código MIT disponível em `C:\Users\Tecnologia\Documents\Projetos\crunchyroll-downloader`. Preserve a licença e registre a procedência de todo código incorporado. O downloader atual não será reutilizado como unidade de download: sua lógica de download integral, chaves globais e descriptografia após concatenação deve ser substituída por materialização independente de segmentos.

## Decisões fixas

### Escopo e plataforma

- Plataforma do servidor neste ciclo: Windows.
- Clientes suportados inicialmente: Chrome atual no desktop e Chrome atual no Android.
- Docker, Linux, macOS, Safari, Firefox e compatibilidade com navegadores antigos ficam fora deste ciclo.
- A Source usa uma conta privada. O cookie `etp_rt` fica em `save.json`, tratado como segredo.
- O catálogo oferece Busca, Popular, Novidades, Temporada, A-Z e Gêneros. Minha Lista, histórico, recomendações, música e concertos ficam fora do escopo.
- Séries e filmes são suportados. A hierarquia de séries é Série -> Temporada -> Episódio.
- O catálogo remoto usa autenticação; metadados persistidos usam TTL de 24 horas e stale-while-revalidate.
- Navegação baixa somente metadados e imagens. Inspecionar manifestos para construir uma apresentação não baixa bytes de áudio ou vídeo.

### Playback

- Shaka Player substitui Plyr e o `<audio>` oculto. Fixar uma versão 5.2.x validada, hospedar JavaScript/CSS no projeto e preservar sua licença Apache-2.0.
- Todo vídeo, áudio e legenda reproduzido usa uma apresentação DASH local estática. Não há caminho alternativo de playback direto por arquivo.
- O MPD local anuncia toda a duração e todas as qualidades, dublagens e legendas descobertas. Anunciar uma faixa não materializa seus bytes.
- O GET de um init segment, media segment ou legenda é a demanda que ativa sua materialização.
- Áudio, legenda, qualidade, volume, fullscreen e picture-in-picture são escolhas individuais de cada navegador.
- Play, pause, seek e velocidade são controlados pelo host e sincronizados globalmente.
- Preferências individuais de faixa são lembradas no navegador. Sem preferência, usa-se a ordem da Source; aplicar o default conta como seleção.
- A primeira legenda configurada é ativada por padrão na primeira visita. A escolha posterior, inclusive `desligada`, é lembrada.
- ABR permanece ativo somente entre `video_quality` e as qualidades inferiores disponíveis.
- Para cada intervalo de vídeo pedido pelo ABR, materializar também o intervalo equivalente da representação canônica definida por `video_quality`. Não preencher trechos pulados.
- Seek para um trecho ausente prioriza diretamente esse trecho; não baixa o intervalo intermediário.
- O player mantém, por padrão configurável, 30 segundos à frente e 30 segundos atrás.
- Buffering do host pausa o relógio lógico da party e retoma automaticamente se a intenção anterior era reproduzir. Buffering isolado de participante não pausa os demais; ele recupera a posição do host.
- Diferenças de até 250 ms não são corrigidas; entre 250 ms e 2 s usa-se ajuste temporário de velocidade; acima de 2 s usa-se seek.
- Trocar para um áudio ausente pode causar buffering apenas naquele navegador até o trecho atual ficar pronto.

### Cache read-through e concorrência

- A unidade de trabalho é `materialize(track, representation, segment_identity)`, não um episódio completo.
- Há uma mídia ativa por Source, até quatro materializações concorrentes de segmentos e, por padrão, até duas sessões remotas de playback.
- Pedidos iguais usam single-flight e compartilham o mesmo artefato e resultado.
- Prioridade: segmento bloqueando playback, buffer próximo das faixas escolhidas e, por último, espelho da qualidade canônica.
- Se o cliente abandonar uma demanda, um segmento remoto já iniciado termina e é validado; demandas ainda na fila e sem consumidores são canceladas.
- Trocar de mídia cancela prefetch e demandas canceláveis da anterior, preservando segmentos completos.
- Uma apresentação substituída expira imediatamente. Requisições atrasadas recebem `410 Gone`, tratado silenciosamente pelo `PlayerController` quando a seleção já mudou.
- Cancelar no painel coloca a apresentação em `download_paused`: recursos prontos continuam reproduzíveis, mas recursos ausentes não reiniciam trabalho até `retomar`.
- Coberturas parciais e segmentos completos permanecem indefinidamente neste ciclo. O schema registra último acesso, tamanho e descartabilidade para permitir LRU/TTL futuro, mas não remove nada automaticamente.
- Segmentos claros são cache derivado e podem ser removidos pelo menu da Crunchyroll. Um MP4 exportado é independente do cache, mas não é usado silenciosamente para reconstruir segmentos.
- Cache parcial continua reproduzível offline nos intervalos presentes; um buraco exige rede e produz estado operacional somente para o host.

### Faixas e exportação manual

- Todas as faixas descobertas aparecem no player; áudio e legenda só são materializados quando algum navegador os seleciona.
- Legendas são baixadas como arquivos completos na primeira seleção. ASS é preservado e convertido para WebVTT.
- O host escolhe exatamente uma representação de vídeo e zero ou mais faixas de áudio e legenda; os padrões da Source aparecem pré-selecionados.
- O job manual completa todos os segmentos ausentes dessa seleção antes de iniciar FFmpeg.
- Áudios e legendas são incorporados como faixas selecionáveis; legendas não são queimadas no vídeo.
- Uploads ASS, SRT e VTT preservam o original e produzem um derivado WebVTT para playback.
- A saída é escrita em pasta temporária e publicada por rename atômico; colisões geram um novo nome e nunca sobrescrevem silenciosamente.
- O job continua se o navegador fechar, mas não sobrevive ao restart do processo. Segmentos completos permanecem no SQLite e um novo job retoma pelos ausentes.

### Segurança e disponibilidade

- Cookie, bearer token, playback token, URLs upstream, licença, chaves e conteúdo do dispositivo Widevine nunca são enviados aos clientes.
- Tokens, licenças e chaves nunca são persistidos. Metadados estruturais persistidos não contêm URLs temporárias.
- Segmentos enviados aos participantes são claros. Impedir que um participante autorizado salve os bytes não é objetivo deste plano.
- IDs de apresentação e recursos são locais, aleatórios ou opacos e confinados à apresentação que os declarou.
- Respostas de participantes são genéricas. Diagnósticos sanitizados e ações operacionais ficam somente no painel do host.
- Worker, FFmpeg, autenticação ou Widevine indisponíveis degradam somente operações dependentes deles.
- Arquivos completos e derivados locais continuam reproduzíveis quando a Crunchyroll estiver indisponível.
- O SQLite oculto é índice derivado. Arquivos, hashes e manifestos são a autoridade para materializações.
- Cada plugin é proprietário de seus derivados. O core não interpreta nem remove o cache da Crunchyroll.

## Fora de escopo

- Limpeza automática, quota, LRU ou TTL de segmentos derivados. Toda limpeza é explícita no menu da Source.
- Autenticação de usuários do WatchParty, URLs assinadas ou DRM no navegador.
- Salas múltiplas e mais de uma party simultânea.

O `host.mjs` da Crunchyroll oferece inventário, download completo selecionável, upload de legendas, exportação MP4 e limpeza agregada. O plugin reutiliza sua materialização tanto para playback quanto para jobs manuais.

## Contrato de configuração

Adicionar uma seção global do `PlaybackModule`:

```json
{
  "playback": {
    "buffer_ahead_seconds": 30,
    "buffer_behind_seconds": 30,
    "segment_wait_timeout_seconds": 30,
    "soft_sync_drift_seconds": 0.25,
    "hard_sync_drift_seconds": 2.0,
    "inactive_playback_grace_seconds": 0
  }
}
```

Registrar `crunchyroll` com estas opções:

```json
{
  "id": "crunchyroll",
  "type": "crunchyroll",
  "label": "Crunchyroll",
  "enabled": true,
  "options": {
    "cache_path": "D:\\CrunchyrollCache",
    "etp_rt": "cookie",
    "locale": "pt-BR",
    "audio_languages": ["pt-BR", "ja-JP"],
    "subtitle_languages": ["pt-BR"],
    "video_quality": "1080p",
    "audio_quality": "192k",
    "metadata_ttl_hours": 24,
    "worker_idle_seconds": 120,
    "max_segment_downloads": 4,
    "max_playback_sessions": 2,
    "worker_path": "bin\\crunchyroll-worker.exe",
    "ffmpeg_path": "ffmpeg.exe",
    "export_path": "D:\\CrunchyrollExports",
    "widevine_device_path": "device.wvd"
  }
}
```

Estender `directory` sem exigir opções novas nas configurações existentes:

```json
{
  "id": "media",
  "type": "directory",
  "label": "Mídia local",
  "enabled": true,
  "options": {
    "path": "D:\\Media",
    "ffmpeg_path": "ffmpeg.exe",
    "transcode_profile": "chrome-h264-aac",
    "hardware_acceleration": "auto"
  }
}
```

Regras:

- Valores de tempo e limites são positivos; `inactive_playback_grace_seconds` é zero neste ciclo.
- `cache_path` aceita caminho absoluto gravável em outro volume. Caminhos relativos são resolvidos a partir do WatchParty.
- `audio_languages` e `subtitle_languages` são ordenados, sem duplicatas. `*` no final inclui idiomas restantes; pelo menos um áudio explícito precede `*`.
- `video_quality` limita o ABR e define a representação canônica; usa a melhor qualidade inferior se a solicitada não existir.
- `max_segment_downloads` limita a fila compartilhada da Source, não cada faixa.
- `max_playback_sessions` limita versões/dublagens remotas abertas simultaneamente.
- `hardware_acceleration: auto` tenta NVENC, Quick Sync e AMF quando compatíveis e usa software como fallback. A falta de aceleração nunca inviabiliza playback por si só.
- O diretório configurado na `DirectorySource` precisa permitir a criação de `.watchparty` para playback. Se não permitir, browse continua disponível e a capability de playback fica indisponível.
- Campos desconhecidos e combinações inválidas falham com `InvalidSourceConfiguration`, sem valores secretos na mensagem.
- Alterar política cria uma nova revisão de apresentação. O SQLite indexa segmentos por mídia, revisão, faixa, representação e identidade.

## Interfaces e módulos

### Interface externa do `PlaybackModule`

O módulo deve oferecer uma Interface pequena aos sockets e rotas. Os tipos abaixo são ilustrativos; os schemas versionados da fase 1 são normativos.

```python
@dataclass(frozen=True)
class PlaybackSelection:
    source_id: str
    media_id: str


@dataclass(frozen=True)
class PlaybackDescriptor:
    playback_id: str
    revision: str
    manifest: MediaResource
    title: str
    image: MediaResource | None


class PlaybackModule:
    async def select(self, selection: PlaybackSelection) -> PlaybackDescriptor: ...
    async def open(self, playback_id: str, resource_id: str, request: ResourceRequest) -> OpenedResource: ...
    async def set_download_paused(self, playback_id: str, paused: bool) -> None: ...
```

Invariantes:

- `select` desativa a apresentação anterior e ativa uma única apresentação idempotente para mídia e política.
- `open` atende MPD, init segments, media segments e legendas sem revelar a origem.
- Abrir MPD nunca materializa bytes audiovisuais.
- Um recurso declarado, mas ausente, é demanda válida; não retorna `404` por ainda não estar cacheado.
- Recurso pronto é imutável naquela revisão e sempre produz os mesmos bytes, tamanho, hash e ETag.
- Nenhum lock global permanece adquirido durante rede, FFmpeg ou envio HTTP.

### Seam interna de origem

`CrunchyrollSource` e `DirectorySource` satisfazem a mesma Interface interna:

```python
class PlaybackOrigin(Protocol):
    async def inspect(self, media_id: str) -> OriginPresentation: ...
    async def materialize(self, media_id: str, demand: SegmentDemand) -> SegmentArtifact: ...
```

`OriginPresentation` normaliza duração, periods, adaptation sets, representações, idiomas, codecs, bandwidth, resolução, init segments, timeline e identidade lógica. `SegmentDemand` pede uma representação e intervalo lógico, nunca uma URL upstream.

O `PlaybackModule` é proprietário de apresentação, MPD local, IDs opacos, lifecycle, respostas HTTP e estado de pausa. Cada Adapter esconde somente como inspeciona e materializa sua origem.

### Contrato de Source restante

- `browse`, `search` e `get_item` continuam responsáveis pelo catálogo.
- `open_resource` permanece para imagens e recursos estáticos publicados.
- Reprodução de vídeo, áudio e legenda usa exclusivamente `PlaybackModule`.
- `SourceSummary.capabilities` distingue browse, search e playback sem revelar detalhes da implementação.

## Contratos de armazenamento

### Cache da Crunchyroll

```text
<cache_path>/
  .crunchyroll/
    cache.json
    catalog.db
    writer.lock
    jobs/
    manifests/
    segments/
      <media-key>/
        <track-key>/
          <representation-key>/
            init.mp4
            segments/
              <segment-key>.m4s
            coverage.json
    incoming/

  <series-id> - <titulo>/
    .source.json
    .previews/
      banner.png
      poster.webp
      backdrop.webp

    Temporada 01/
      .source.json
      .previews/
        banner.png

      <episode-id> - S01E01 - <titulo>.mp4

      .dubs/
        <mesmo-stem>.en-US.m4a

      .subs/
        <mesmo-stem>.pt-BR.vtt

      .subs-original/
        <mesmo-stem>.pt-BR.ass

      .previews/
        <mesmo-stem>_banner.png
```

Regras:

- Downloads entram em `incoming` com nome não público; somente artefatos completos, descriptografados e validados são movidos atomicamente para `segments`.
- `coverage.json` registra identidade, timeline, estado `missing|queued|fetching|ready|failed`, hash, tamanho, tentativas, último acesso e última mudança.
- Nunca persistir cookie, URL CDN, playback token, licença ou chave nos manifestos, SQLite, nomes, exceções ou logs.
- `.source.json` registra objeto remoto, recursos públicos, política de publicação e revisões usadas.
- O manifesto público só declara `complete` depois de validar MP4 e recursos obrigatórios. Recursos tardios atualizam o manifesto atomicamente.
- `catalog.db` indexa catálogo, relações, páginas, pesquisas e estado derivado. Se removido ou corrompido, é reconstruído dos manifestos e, quando possível, da API.
- `cache.json` contém schema, identidade proprietária, conta/região não secreta, política ativa e histórico de políticas.
- Nomes são sanitizados para Windows e truncados antes do limite; o ID remoto nunca é removido.
- Títulos atualizados aparecem no manifesto; arquivos completos não são renomeados.

### Cache derivado da `DirectorySource`

```text
<directory-root>/
  .watchparty/
    playback/
      schema.json
      index.db
      writer.lock
      artifacts/
        <file-fingerprint>/
          <transcode-profile>/
            manifest-data.json
            init/
            segments/
            subtitles/
```

Regras:

- O original é a autoridade. `.watchparty` contém somente derivados reconstruíveis e é ignorado por browse.
- Fingerprint inclui caminho resolvido, tamanho, `mtime`, identidade de streams e versão do empacotador. Perfil de transcode faz parte da chave.
- Duas Sources na mesma raiz compartilham derivados; um lock coordena escritor e múltiplos leitores continuam permitidos.
- Alterar o original invalida a revisão sem modificar nem apagar o arquivo original.
- Falta de escrita torna playback indisponível, mas não impede browse ou startup.
- Não há fallback silencioso para cache central.
- Não há remoção automática neste ciclo. Falta de espaço falha a materialização, preserva artefatos completos e informa o host.

## Manifesto DASH e transporte HTTP

- Produzir MPD VOD `type="static"` com duração e timeline completas.
- Inspecionar sequencialmente e cachear a estrutura das versões/dublagens antes de `set_video`; liberar cada sessão de inspeção imediatamente.
- Falha de faixa opcional não invalida a mídia: omitir a faixa daquela revisão e avisar o host.
- O MPD contém somente URLs locais e não contém `ContentProtection`, PSSH ou dados remotos.
- Segmentos fMP4 e init segments servidos ao navegador já estão descriptografados.
- O endpoint de asset espera até `segment_wait_timeout_seconds`. Se o prazo expirar, responde `503` com `Retry-After`; Shaka executa uma rodada curta de retry.
- Download pausado responde com estado distinto e esperado pelo `PlayerController`; não gera notificação genérica repetida.
- MPD usa ETag e revalidação. Assets imutáveis usam ETag pelo hash e cache privado longo.
- `GET` e `HEAD` são suportados. Range permanece disponível para recursos estáticos que o Adapter declare, mas playback não depende de arquivo crescente ou tamanho mutável.
- `404` significa ID inexistente; `410`, apresentação inativa; `416`, Range inválido; `422`, mídia não suportada; `503`, indisponibilidade/retry; `500`, falha sanitizada.
- Segmentos nunca são transmitidos enquanto crescem e nunca são publicados sem hash e validação.

Rotas alvo:

```text
POST /api/playbacks
PUT  /api/playbacks/<playback-id>/download-state
GET  /media/playbacks/<playback-id>/manifest.mpd
GET|HEAD /media/playbacks/<playback-id>/assets/<opaque-asset-id>
```

O socket `set_video` envia o mesmo `playback_id`, `revision` e `manifest_url` opacos para todos. Somente o servidor ativa a Source. Reconexões reutilizam a apresentação ativa; navegadores nunca criam ativações duplicadas.

## `DirectoryPlaybackAdapter`

- Usar FFprobe para indexar duração, keyframes, vídeo, áudios internos, sidecars e legendas.
- Produzir timeline e boundaries determinísticos antes de publicar o MPD.
- Gerar somente init e segmentos demandados, inclusive depois de seek arbitrário.
- Usar stream copy quando contêiner, codec, timestamps e keyframes permitirem.
- Remuxar MP4/WebM/MKV compatíveis para fMP4/CMAF sem alterar o original.
- Transcodificar AVI ou codec incompatível para H.264/AAC, forçando boundaries reproduzíveis e parâmetros estáveis entre segmentos.
- Detectar aceleração de hardware configurada e usar software como fallback.
- Transformar áudios internos e M4A sidecars em adaptation sets na mesma timeline.
- Converter legenda sob demanda e expô-la como faixa DASH; não usar player de áudio separado.
- Se um MP4 público da Crunchyroll existir e seus segmentos derivados estiverem ausentes, regenerá-los localmente por este caminho, sem rede.

## Worker Go da Crunchyroll

Criar `tools/crunchyroll-worker/` importando somente código necessário e preservando licença/atribuição.

### Processo e protocolo

- Um processo persistente atende uma mídia ativa. Recebe comandos JSON Lines versionados no `stdin`, emite somente eventos/respostas JSON Lines no `stdout` e envia diagnósticos sanitizados ao `stderr`.
- Cookie entra no comando inicial pelo `stdin`, nunca pela linha de comando.
- Comandos mínimos: `activate`, `inspect_version`, `materialize`, `cancel_queued`, `release`, `shutdown`.
- Cada comando e evento carrega versão, request ID, media key e correlation ID; respostas fora de ordem são permitidas.
- Eventos mínimos: `started`, `stage`, `progress`, `warning`, `asset`, `retrying`, `completed`, `failed`, `released`.
- Após `worker_idle_seconds` sem demandas, liberar sessões e encerrar. Nova demanda cria processo usando o cache persistido.
- Desativação cancela fila, permite terminar segmentos já iniciados, libera sessões e encerra. Exportações em andamento são jobs transitórios do plugin.

### MPD, DRM e materialização

- Implementar parser temporal completo de `SegmentTemplate` e `SegmentTimeline`: `$Number$`, `$Time$`, `$RepresentationID$`, `T`, `D`, `R`, `Timescale`, `PresentationTimeOffset` e `StartNumber`.
- Identificar adaptation sets por `contentType`, MIME, roles e codecs, nunca pela posição no XML.
- Persistir descrição normalizada de cada representação e timeline, sem URLs temporárias.
- Cada versão/dublagem possui `LicenseContext` imutável e key set por KID. Remover chaves globais.
- Validar KID -> key explicitamente; nunca escolher apenas a primeira chave `CONTENT` sem conferir o fragmento.
- Descriptografar/canonizar init uma vez e cada media segment isoladamente com `mp4ff`, publicando-os separadamente.
- Nunca manter o episódio completo nem todos os segmentos em RAM; usar chunks e backpressure.
- Abrir playback/licença somente sob demanda, respeitar `max_playback_sessions` e liberar sessões inativas.
- Reabrir playback, manifesto e licença em expiração, 401/403 ou URL CDN inválida. Distinguir bearer expirado de URL temporária expirada.
- Liberar playback por `DELETE` em sucesso, falha, cancelamento e ociosidade.
- Tratar 420, 429, 4294, `Retry-After` e limites de streams com pacing e backoff.
- Fazer até cinco tentativas por segmento, com backoff, jitter e `Retry-After`; depois devolver falha tipada ao Playback Module.
- A fila compartilhada limita quatro transferências, deduplica por identidade e preserva prioridade de playback sobre canônica.
- Legendas ASS são arquivos completos e só são baixadas na primeira seleção.
- Imagens e metadados de catálogo vêm do cliente Python/API, pois o downloader de referência não os modela.

## Scheduler, cobertura e exportação manual

O plugin Crunchyroll possui SQLite e blob store próprios; o worker é Adapter da origem remota. O `PlaybackModule` não cria uma segunda cópia desses artefatos.

- Registrar demandas e consumidores sem expor detalhes do worker ao HTTP.
- Coalescer pedidos concorrentes numa future single-flight.
- Cancelar demandas sem consumidores apenas enquanto ainda estão na fila.
- Ao demandar vídeo no intervalo T, agendar também a representação canônica que cobre T; deduplicar quando for a mesma.
- Registrar segmentos completos atomicamente e reconciliar banco, temporários e órfãos no startup.
- Um novo playback sob política diferente cria revisão nova e reutiliza segmentos cuja identidade é compatível.
- Download manual usa as faixas selecionadas e preserva prioridade do playback.
- Exportação roda somente por ação do host, completa ausências, cria snapshot de entradas e usa arquivos temporários confinados.
- Falha de FFmpeg preserva segmentos para nova tentativa e nunca deixa saída pública parcial.

## Player, sockets e interface

- Criar `PlayerController` como Adapter fino sobre Shaka. Sockets e sincronização dependem apenas de `load`, `play`, `pause`, `seek`, `playbackRate`, seleção de faixas e eventos normalizados.
- Remover Plyr e o `<audio>` oculto; não manter fallback visual ou técnico antigo.
- Hospedar bundle, CSS e arquivos de licença do Shaka localmente; não usar URL `latest`.
- Configurar preferências antes de carregar o MPD e persistir escolhas por Source no navegador.
- Expor menus de áudio, legenda e qualidade do Shaka; limitar variantes à qualidade máxima configurada.
- Traduzir `waiting`, `buffering` e `playing` do host em pausa/retomada lógica sem perder a intenção do usuário.
- Sincronizar velocidade do host e aplicar correção suave/seek segundo os thresholds globais.
- Um participante que recupera buffer volta ao relógio do host sem pausar a party.
- Tratar `410` de apresentação antiga, aborts, retries e download pausado como lifecycle esperado, sem mensagens de erro ao usuário.
- Host vê cobertura por faixa, bytes armazenados, jobs desta execução, exportações e simulação de limpeza.
- Participantes veem somente carregamento e falhas genéricas; nunca recebem caminhos, cookies, URLs temporárias ou detalhes DRM.
- Manter ações de pausar materialização, retomar e tentar novamente no painel do host.

## Arquitetura alvo

### Python

- `src/playback/models.py`: apresentações, recursos, tracks, demandas, cobertura, erros e schemas.
- `src/playback/module.py`: Interface externa, lifecycle, revisão, ativação e pausa.
- `src/playback/manifest.py`: geração de MPD local estático e IDs opacos.
- `src/playback/scheduler.py`: prioridade, single-flight, consumidores, retries e `MaterializationPlanner`.
- `src/playback/store.py`: artefatos, hashes, cobertura, reconciliação e locks.
- `src/playback/http.py` ou rotas equivalentes: manifesto e assets.
- `src/media_sources/plugins/directory/source_core.py`: browse, recursos e convenções `.previews`.
- `src/media_sources/plugins/directory/playback.py`: FFprobe, segmentação, remux e transcode.
- `src/media_sources/plugins/directory/backend.py` e `host.mjs`: factory e ferramentas administrativas.
- `src/media_sources/plugins/crunchyroll/catalog_core.py`: catálogo, busca e resolução.
- `src/media_sources/plugins/crunchyroll/api.py`: autenticação, pacing, retry e redaction.
- `src/media_sources/plugins/crunchyroll/cache.py`: SQLite, segmentos, anexos, exportações e limpeza.
- `src/media_sources/plugins/crunchyroll/worker_client.py`: processo persistente e protocolo JSON Lines.
- `src/media_sources/plugins/crunchyroll/source.py` e `host.mjs`: Adapter gerenciado e painel específico.
- `src/media_sources/registry.py`: factories, capabilities e validação.

Os nomes podem mudar durante implementação, mas a seam `PlaybackModule` -> `PlaybackOrigin` e a separação entre cache derivado e autoridade pública são obrigatórias.

### Frontend

- `files/vendor/shaka/`: versão fixada, UI, CSS e licença.
- `files/modules/player-controller.js`: Adapter sobre Shaka.
- `files/modules/video-sync.js`: sincronização sem conhecimento de Source ou Shaka direto.
- `files/host.js` e painel: seleção, cobertura, pausa, retomada, retry e avisos.

### Worker

- `tools/crunchyroll-worker/`: protocolo, MPD, sessões, DRM, materialização e testes Go.
- `bin/crunchyroll-worker.exe`: saída padrão do build Windows, não versionada se privada.

## Sequência de implementação

### 1. Congelar contratos e fixtures

1. Versionar schemas de configuração, apresentação, MPD normalizado, demanda, segmento, cobertura, job, manifesto público e protocolo do worker.
2. Criar fixtures de MPD com `$Number$`, `$Time$`, timelines irregulares, múltiplos periods, adaptation sets fora de ordem, KIDs e versões de dublagem distintas.
3. Criar fixtures de catálogo para série, temporada, episódio, filme, paginação, idiomas ausentes e rate limits.
4. Criar árvores fixture para cache Crunchyroll parcial/completo e cache `.watchparty`.
5. Criar fake clock, origin Adapter em memória, worker fake e FFmpeg fake.

Critério: schemas e invariantes têm exemplos; nenhuma fixture comum chama Crunchyroll, Widevine ou CDN real.

### 2. Implementar o `PlaybackModule`

1. Criar modelos, erros, lifecycle, revisões e Interface interna `PlaybackOrigin`.
2. Implementar MPD DASH local estático com IDs opacos e sem segredos.
3. Implementar `MaterializationPlanner`, single-flight, prioridades, pausa e cancelamento de fila.
4. Implementar `SegmentStore`, hashes, publicação atômica e reconciliação.
5. Criar endpoints GET/HEAD, timeout, ETag, cache headers e mapeamento de erros.
6. Testar tudo pelo Adapter em memória através da Interface pública.

Critério: um manifesto anuncia assets ausentes; a primeira leitura cria exatamente um trabalho; concorrência compartilha resultado; `410`, pausa, retry e Range obedecem ao contrato.

### 3. Substituir o player e a sincronização

1. Fixar e hospedar Shaka Player/UI/CSS/licença.
2. Criar `PlayerController` e remover Plyr e áudio oculto.
3. Implementar preferências individuais, default configurado, ABR limitado, legendas e troca de áudio.
4. Implementar buffering global do host, recuperação individual e sincronização suave.
5. Mudar `set_video` para descriptor opaco compartilhado.
6. Adicionar testes de frontend com Shaka fake e Playwright no Chrome.

Critério: vídeo, áudio alternativo e legenda usam a mesma timeline; não existe `<audio>` auxiliar; dois clientes escolhem faixas distintas e continuam sincronizados.

### 4. Adaptar a `DirectorySource`

1. Preservar browse, confinamento, imagens, M4A, recursos publicados e `.source.json`.
2. Implementar `.watchparty/playback`, schema, fingerprint, lock e cache derivado.
3. Implementar FFprobe, keyframe index e timeline determinística.
4. Implementar materialização arbitrária por segmento com stream copy, remux e transcode.
5. Implementar aceleração auto com fallback software e invalidação por alteração do original/perfil.
6. Cobrir MP4, MKV, WebM, AVI, faixas internas, sidecars e VTT.

Critério: toda mídia suportada abre via DASH/Shaka; seek distante materializa somente o intervalo pedido; raiz read-only continua navegável e anuncia playback indisponível.

### 5. Implementar catálogo e cache da Crunchyroll

1. Validar configuração e registrar a factory `crunchyroll`.
2. Implementar autenticação e renovação em memória a partir de `etp_rt`.
3. Implementar Busca, Popular, Novidades, Temporada, A-Z, Gêneros, série, temporada, episódio e filme.
4. Implementar TTL, stale-while-revalidate, pacing, backoff e catálogo offline.
5. Implementar layout, owner lock, manifestos, SQLite derivado, reconciliação e redaction.
6. Implementar inspeção sequencial/cacheada de versões sem baixar mídia.

Critério: catálogo funciona contra transportes simulados, continua navegável offline e nunca persiste ou exibe segredo.

### 6. Construir o worker segmentado

1. Importar código necessário com licença e atribuição.
2. Implementar protocolo bidirecional persistente e lifecycle por mídia.
3. Substituir parser MPD simplificado por timeline completa e seleção sem dependência de ordem.
4. Implementar contextos de licença por versão e mapa KID -> key sem globals.
5. Implementar init e media segments independentes, descriptografia por fragmento e publicação clara.
6. Implementar sessions, limites, idle, release, refresh, retry e cancelamento.
7. Garantir stdout exclusivamente JSON e redaction em todos os fluxos.
8. Adicionar build Windows reproduzível.

Critério: dois áudios podem ser materializados concorrentemente com chaves distintas; seek baixa um segmento isolado; restart reutiliza cache claro; sessões são sempre liberadas.

### 7. Integrar scheduler, cobertura e qualidade canônica

1. Conectar demandas HTTP ao worker persistente.
2. Implementar quatro transferências, duas sessões, prioridade e single-flight.
3. Implementar espelho canônico por intervalo temporal, inclusive entre timelines desalinhadas.
4. Implementar pausa/retomada, worker idle e política de cinco tentativas.
5. Persistir cobertura e progresso por representação/faixa.
6. Implementar troca de política com revisão e reaproveitamento compatível.

Critério: ABR em duas qualidades produz somente os segmentos demandados e a canônica correspondente; troca de episódio cancela fila antiga; segmento iniciado termina uma única vez.

### 8. Implementar download e exportação manuais

1. Exibir todas as qualidades, áudios e legendas, pré-selecionando a configuração.
2. Completar sob demanda a seleção do host e registrar cobertura no SQLite.
3. Aceitar ASS, SRT e VTT locais, preservando original e VTT derivado.
4. Executar FFmpeg somente após `Salvar como MP4`.
5. Publicar MP4 e sidecars atomicamente no `export_path` sem sobrescrita silenciosa.
6. Manter jobs somente em memória e reutilizar segmentos completos após restart.

Critério: nenhuma cobertura inicia exportação sozinha; falha em qualquer etapa não expõe MP4 parcial.

### 9. Integrar painel e estados operacionais

1. Adicionar busca e paginação ao painel.
2. Renderizar coleções virtuais e imagens nomeadas.
3. Mostrar cobertura, bytes, faixas, jobs, exportações e limpeza ao host.
4. Adicionar pausar materialização, retomar e tentar novamente.
5. Tratar lifecycle esperado sem notificações espúrias.
6. Manter participantes livres de detalhes operacionais sensíveis.

Critério: host pesquisa, seleciona, assiste durante download, troca faixa, busca trecho ausente, pausa materialização e retoma; participantes recebem somente estados genéricos.

### 10. Endurecer disponibilidade e segurança

1. Separar health de catálogo, worker, FFmpeg, Widevine, autenticação, cache e playback.
2. Testar traversal, symlink/junction, IDs cruzados, roots read-only e falta de espaço.
3. Testar corrupção, truncamento, crash, restart, sessão expirada e rate limits.
4. Testar redaction de cookie, tokens, URLs, licenças, chaves, query strings e paths.
5. Testar concorrência entre `CrunchyrollSource`, `DirectorySource`, readers e writers.
6. Validar shutdown interrompendo jobs transitórios, removendo temporários e liberando sessões.

Critério: aplicação inicia com dependências remotas ausentes; cache completo e intervalos parciais disponíveis continuam reproduzíveis; nenhum teste ou log contém segredo.

### 11. Documentar e empacotar para Windows

1. Atualizar `save.example.json` com `playback`, `crunchyroll` e opções novas de `directory`, sem credenciais.
2. Documentar configuração local do cookie e dispositivo Widevine sem registrar conteúdo.
3. Documentar Shaka hospedado, licenças, build do worker, FFmpeg e aceleração opcional.
4. Documentar caches `.crunchyroll` e `.watchparty`, permissões, falta de espaço, exclusão manual e reconstrução.
5. Documentar cache SQLite, jobs transitórios, exportação manual e sidecars.
6. Documentar plugins de Source, `host.mjs` e namespace `/host/<source_id>/<action>`.
7. Confirmar que `save.json`, dispositivos Widevine, binários privados, logs e temporários não entram no Git.

Critério: instalação Windows limpa pode ser configurada somente pelo README; artefatos versionados e histórico Git não contêm segredos.

## Matriz mínima de verificação

- Configuração: defaults globais, limites, listas, wildcard, paths Windows, aceleração e campos extras.
- Contrato: mesmas suítes contra origin em memória, `DirectoryPlaybackAdapter` e `CrunchyrollPlaybackAdapter` simulado.
- MPD: timeline completa, `$Number$`, `$Time$`, periods, adaptation sets fora de ordem, todas as faixas e ausência de DRM/URLs remotas.
- Demanda: cache miss/hit, single-flight, quatro transferências, prioridades, abandono, pausa e retomada.
- HTTP: GET, HEAD, ETag, cache, Range declarado, timeout, 404, 410, 416, 422 e 503/retry.
- ABR: limite superior, fallback inferior, duas representações usadas e espelho canônico somente nos intervalos vistos.
- Seek: início, fim, salto distante e timelines desalinhadas sem preencher buracos.
- Faixas: preferência local, default, áudio simultâneo por usuário, legenda sob demanda e ausência opcional.
- DRM: contextos concorrentes, KID correto, licença renovada, segredo somente em memória e release em todos os caminhos.
- Cache: hash, rename atômico, cobertura esparsa, corrupção, crash, restart, read-only, disco cheio e política nova.
- Offline: segmento parcial presente, buraco ausente, MP4 completo e regeneração local de derivados.
- Directory: MP4, MKV, WebM, AVI, keyframes, remux, transcode, hardware fallback, sidecars e alteração do original.
- Exportação manual: seleção de faixas, conclusão de ausências, snapshot, FFmpeg, publicação atômica e falha por etapa.
- Sincronização: host buffering, participante buffering, drift suave, hard seek, velocidade global e reconexão.
- Segurança: traversal, IDs de outra apresentação, symlink/junction, redaction e cookie fora de argv/stdout/respostas.
- UI: busca, cobertura, seleção individual de faixa, qualidade, pausa, retry e ausência de erros esperados.

## Definição de pronto

A implementação está pronta quando todas as fases e critérios estiverem satisfeitos, a suíte anterior continuar verde e um teste de aceitação local no Windows demonstrar:

1. configurar cache Crunchyroll em outro volume e uma `DirectorySource` gravável;
2. iniciar com cache vazio, pesquisar uma série e navegar até um episódio;
3. selecionar o episódio e ver todas as faixas descobertas sem baixar todas elas;
4. iniciar playback após o buffer inicial enquanto segmentos são materializados;
5. usar ABR, confirmar limite de qualidade e cache canônico somente nos trechos vistos;
6. trocar áudio e legenda individualmente em dois clientes sem player de áudio auxiliar;
7. fazer seek para trecho distante sem baixar o intervalo pulado;
8. pausar materialização, reproduzir trecho cacheado, atingir um buraco e retomar;
9. reiniciar sem rede e reproduzir intervalos parciais presentes;
10. assistir cobertura completa de vídeo canônico e de ao menos um áudio;
11. avançar o relógio de teste pela quietude configurada e gerar MP4 com áudio escolhido pela prioridade;
12. completar outro áudio depois e publicá-lo como M4A sem reescrever MP4;
13. abrir o cache público pela `DirectorySource` e reproduzir MP4, áudio e legenda pela mesma Interface DASH;
14. reproduzir MP4/MKV/WebM/AVI locais, exercitando stream copy, remux e transcode;
15. reiniciar com política diferente e reaproveitar segmentos compatíveis sem expor segredos.
