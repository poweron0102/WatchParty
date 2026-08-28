# Plano de implementação: `CrunchyrollSource`

Status: aprovado para planejamento; implementação ainda não iniciada.

## Resultado esperado

Adicionar ao WatchParty uma Source privada para pesquisar e navegar pelo catálogo da Crunchyroll, preparar mídias sob demanda e reproduzi-las a partir de um cache permanente escolhido pelo usuário. O cache deve continuar navegável por uma `DirectorySource`, inclusive quando a autenticação ou a API remota estiver indisponível.

Este plano usa o código MIT disponível em `C:\Users\Tecnologia\Documents\Projetos\crunchyroll-downloader` como base para um worker Go local. Preserve a licença e registre a procedência de todo código incorporado.

## Decisões fixas

- Plataforma inicial: Windows. Docker, Linux e macOS ficam fora deste ciclo.
- A Source usa uma conta privada. O cookie `etp_rt` fica em `save.json`, que passa a ser tratado como segredo.
- O catálogo inicial oferece Busca, Popular, Novidades, Temporada, A-Z e Gêneros. Minha Lista, histórico, recomendações, música e concertos ficam fora do escopo.
- O catálogo remoto usa autenticação; metadados persistidos usam TTL de 24 horas e stale-while-revalidate.
- Séries e filmes são suportados. A hierarquia de séries é Série -> Temporada -> Episódio.
- Navegação baixa somente metadados e imagens. A seleção de uma mídia ausente inicia sua preparação.
- Há no máximo um download ativo por Source. Pedidos iguais são deduplicados.
- O primeiro idioma configurado que existir no episódio é incorporado ao MP4. Os demais áudios ficam em sidecars M4A.
- A qualidade solicitada tem fallback para a melhor qualidade inferior disponível.
- Legendas ASS são preservadas e convertidas para WebVTT para o player atual.
- Arquivos completos são permanentes: o programa não remove nem renomeia mídias automaticamente.
- Downloads parciais podem ser cancelados e retomados. Tokens, licenças e chaves nunca são persistidos.
- O SQLite oculto é um índice derivado. Arquivos e manifestos são a autoridade para mídias materializadas.
- Uma `CrunchyrollSource` escreve no cache; uma `DirectorySource` pode lê-lo ao mesmo tempo.

## Contrato de configuração

Registrar o tipo `crunchyroll` com estas opções:

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
    "worker_path": "bin\\crunchyroll-worker.exe",
    "ffmpeg_path": "ffmpeg.exe",
    "widevine_device_path": "device.wvd"
  }
}
```

Regras:

- `cache_path` aceita qualquer caminho absoluto gravável, incluindo outro volume. Caminhos relativos são resolvidos a partir do diretório do WatchParty.
- `audio_languages` e `subtitle_languages` são listas ordenadas, sem duplicatas. `*` no final inclui os idiomas restantes.
- Pelo menos um idioma de áudio explícito deve preceder `*`.
- `metadata_ttl_hours` deve ser positivo.
- Caminhos de worker, FFmpeg e Widevine podem ser absolutos ou relativos.
- Campos desconhecidos e combinações inválidas falham com `InvalidSourceConfiguration`, sem incluir valores secretos na mensagem.
- Worker, FFmpeg, autenticação ou Widevine indisponíveis degradam somente as operações que dependem deles. O servidor inicia e continua servindo arquivos completos do cache.

## Contrato do cache

O layout público deve obedecer às convenções da `DirectorySource`:

```text
<cache_path>/
  .crunchyroll/
    cache.json
    catalog.db
    writer.lock
    jobs/
    partial/

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

Regras de autoridade:

- `.source.json` identifica o objeto remoto, registra os recursos publicados e a política efetivamente usada.
- O manifesto é gravado por último e só declara `complete` depois que todos os recursos obrigatórios foram validados.
- Sidecars e imagens são publicados antes do MP4. O MP4 é movido por último, de modo que uma `DirectorySource` nunca descubra um vídeo antes de seus recursos prontos.
- `catalog.db` indexa catálogo, relações, respostas paginadas e pesquisas. Se removido ou corrompido, é reconstruído a partir dos manifestos locais e, quando possível, da API.
- `cache.json` contém versão do esquema, identidade da Source proprietária, política ativa e histórico de políticas usadas. A mesma Source pode trocar sua política para downloads futuros; outra Source com conta, região ou política incompatível não adquire o lock de escrita.
- Nomes são sanitizados para Windows e truncados antes de atingir o limite de caminho. O ID remoto nunca é removido do nome.
- Títulos atualizados aparecem pelo manifesto; arquivos completos não são renomeados.

## Arquitetura alvo

### Python

- `src/media_sources/crunchyroll.py`: implementa catálogo, busca, resolução de itens e abertura de recursos.
- `src/media_sources/crunchyroll_api.py`: autenticação, cliente HTTP, paginação, pacing, retry e redaction.
- `src/media_sources/crunchyroll_cache.py`: layout, manifestos, índice derivado, reconciliação e publicação.
- `src/media_sources/crunchyroll_jobs.py`: fila, deduplicação, cancelamento, retomada e eventos de progresso.
- `src/media_sources/crunchyroll_worker.py`: valida e controla o processo Go.
- `src/media_sources/models.py`: adiciona busca, estado de preparação e imagens nomeadas sem remover os campos compatíveis atuais.
- `src/media_sources/registry.py`: registra a factory `crunchyroll` e valida suas opções.

### Worker Go

Criar `tools/crunchyroll-worker/` a partir das partes necessárias do downloader de referência:

- troca do cookie por token;
- consulta de playback e liberação de sessões;
- seleção de versões, idiomas e qualidades;
- MPD, segmentos, Widevine e descriptografia;
- download de ASS e imagens necessárias;
- remux do primeiro áudio disponível para MP4;
- emissão de áudios adicionais em M4A;
- conversão ASS -> WebVTT por FFmpeg;
- retomada de segmentos validados.

O worker executa um trabalho por processo. Recebe um JSON versionado pelo `stdin`, emite somente eventos JSON Lines no `stdout` e envia diagnósticos para `stderr`. O cookie entra pelo `stdin`, nunca pela linha de comando. Eventos mínimos: `started`, `stage`, `progress`, `warning`, `asset`, `completed` e `failed`. Cancelamento encerra o processo e preserva segmentos válidos.

### HTTP, sockets e interface

- Acrescentar `search(query, cursor)` ao contrato de Source e expor uma rota de busca paginada.
- Expor estado e progresso dos trabalhos somente ao host.
- A seleção de conteúdo ausente cria ou reutiliza um trabalho; `set_video` é emitido apenas após conclusão.
- Acrescentar ações de cancelar e tentar novamente no painel do host.
- Manter respostas dos participantes genéricas. O host recebe mensagens operacionais sanitizadas.
- Preservar `CatalogEntry.image` e `MediaItem.image` como imagem principal e acrescentar recursos nomeados para poster, backdrop e thumbnail.

## Sequência de implementação

### 1. Congelar contratos e fixtures

1. Documentar os schemas versionados de configuração, manifesto, job e protocolo do worker.
2. Criar fixtures mínimas para série, temporada, episódio, filme, paginação, idiomas ausentes e respostas de limite temporário.
3. Criar uma árvore de cache fixture no formato alvo.
4. Adicionar um teste que abra essa árvore com `DirectorySource` e encontre vídeo, áudio, legenda e imagens.

Critério de conclusão: todos os schemas têm versão e exemplos; o teste de compatibilidade falha antes das mudanças de M4A/imagens e representa o layout aprovado.

### 2. Evoluir os contratos de Source

1. Adicionar modelos para imagens nomeadas, busca paginada e estado de preparação.
2. Acrescentar `search` ao protocolo sem quebrar Sources existentes; Sources sem busca anunciam a ausência dessa capability.
3. Estender `DirectorySource` para M4A e manter as regras atuais de confinamento e HTTP Range.
4. Atualizar serialização, registry, testes de contrato e `SourceSummary.capabilities`.

Critério de conclusão: `DirectorySource` passa em toda a suíte anterior e na fixture nova; uma Source sem busca continua registrável e utilizável.

### 3. Implementar o cache permanente

1. Resolver e validar `cache_path` sem restringi-lo ao volume do projeto.
2. Implementar manifests, sanitização, truncamento, identidade do proprietário, histórico de políticas e lock de escritor.
3. Implementar o SQLite derivado, migrações de esquema e reconstrução.
4. Implementar reconciliação completa no startup e validação pontual antes da reprodução.
5. Implementar publicação com sidecars primeiro, MP4 por último e manifesto `complete` no final.

Critério de conclusão: apagar `catalog.db` e reiniciar reconstrói todo conteúdo materializado; apagar manualmente um MP4 faz o item voltar a `not_downloaded`; nenhum arquivo parcial aparece para `DirectorySource`.

### 4. Criar o cliente de catálogo

1. Implementar autenticação e renovação em memória a partir de `etp_rt`.
2. Implementar Busca, Popular, Novidades, Temporada, A-Z, Gêneros, série, temporada, episódio e filme.
3. Normalizar IDs, locale, cursores e imagens.
4. Aplicar TTL, stale-while-revalidate, pacing e backoff.
5. Servir catálogo persistido quando autenticação ou rede falharem.

Critério de conclusão: todos os ramos de catálogo funcionam contra transportes simulados; depois de populado, o catálogo continua navegável com o transporte desligado; nenhum teste comum chama a API real.

### 5. Adaptar o worker Go

1. Importar apenas o código necessário e preservar licença/atribuição.
2. Remover flags, globals, `panic` como controle normal e escrita no diretório corrente.
3. Implementar o protocolo JSON e erros estruturados.
4. Produzir MP4 com o primeiro áudio configurado disponível, M4A adicionais, ASS original, VTT e imagens.
5. Persistir segmentos criptografados com hashes; reabrir playback/licença na retomada.
6. Garantir liberação das sessões de playback em sucesso, falha e cancelamento.
7. Adicionar script de build Windows e saída padrão `bin/crunchyroll-worker.exe`.

Critério de conclusão: testes Go cobrem seleção ordenada de áudio, wildcard, qualidade inferior, idiomas ausentes, retry, cancelamento, retomada e limpeza de sessões; stdout contém somente JSON válido; segredos não aparecem nos fluxos capturados.

### 6. Implementar fila e integração do worker

1. Persistir estados `queued`, `running`, `cancelled`, `failed` e `complete` em `.crunchyroll/jobs`.
2. Garantir uma execução ativa, deduplicação por conteúdo/política e retomada após reinício.
3. Validar cada asset informado pelo worker antes da publicação.
4. Permitir anexar faixas opcionais a uma mídia completa sem reescrever o MP4.
5. Manter qualidade e áudio incorporado existentes quando a configuração mudar.

Critério de conclusão: solicitações simultâneas criam um único processo; reiniciar durante um trabalho permite retomada; falha de faixa opcional não invalida o episódio; ausência de todos os áudios configurados falha sem publicar o MP4.

### 7. Integrar rotas, sockets e painel do host

1. Adicionar busca e paginação ao painel.
2. Renderizar coleções virtuais e imagens por função.
3. Exibir progresso, etapa, avisos, cancelamento e nova tentativa.
4. Adiar `set_video` até o item estar completo.
5. Manter participantes e logs remotos livres de detalhes sensíveis.

Critério de conclusão: um host consegue pesquisar, navegar, preparar, cancelar, retomar e selecionar uma mídia; participantes nunca recebem cookie, caminhos, URLs temporárias, tokens ou mensagens DRM detalhadas.

### 8. Endurecer disponibilidade e segurança

1. Separar health de catálogo, worker, FFmpeg, Widevine e autenticação.
2. Permitir leitura do cache quando qualquer dependência remota ou de download falhar.
3. Redigir cookies, tokens, licenças, chaves e query strings sensíveis em exceções e logs.
4. Validar que IDs, nomes e caminhos recebidos não escapam de `cache_path`.
5. Testar locks, corrupção do índice, arquivos ausentes, respostas truncadas e encerramento inesperado do worker.

Critério de conclusão: a aplicação inicia com worker ou Widevine ausente; recursos completos continuam com Range; testes de traversal, redaction e concorrência passam.

### 9. Documentar e empacotar para Windows

1. Atualizar `save.example.json` sem credenciais reais.
2. Documentar obtenção/configuração local do cookie e do dispositivo Widevine sem registrar seus conteúdos.
3. Documentar build do worker, FFmpeg, caminhos absolutos em outros volumes e permissões.
4. Documentar formato do cache, exclusão manual, mudança de política e recuperação do índice.
5. Confirmar que `save.json`, dispositivos Widevine, binários privados, logs e parciais não entram no Git.

Critério de conclusão: uma instalação Windows limpa pode ser configurada seguindo apenas o README; o exemplo versionado e o histórico Git não contêm segredos.

## Matriz mínima de verificação

- Registry: opções válidas, campos extras, locale, listas, wildcard e paths Windows.
- Catálogo: cada coleção raiz, busca vazia, paginação, cursor inválido, TTL e modo offline.
- Compatibilidade: cache aberto por `CrunchyrollSource` e `DirectorySource` com os mesmos assets públicos.
- Recursos: GET, HEAD, ranges abertos/fechados/sufixos, conteúdo vazio e arquivo removido.
- Idiomas: primeiro disponível, fallback ordenado, wildcard, faixa opcional ausente e nenhum áudio válido.
- Jobs: deduplicação, serialização, cancelamento, retomada, crash e reinício do servidor.
- Limites remotos: 420, 429, 4294, `Retry-After`, backoff esgotado e liberação de playback.
- Publicação: falha em cada etapa não expõe MP4; sucesso publica vídeo por último.
- Segurança: traversal, symlink/junction, nomes reservados do Windows, redaction e cookie fora da linha de comando.
- Interface: busca, progresso, cancelamento, retry, imagens e emissão tardia de `set_video`.

## Definição de pronto

A implementação está pronta quando todas as fases e critérios acima estiverem satisfeitos, a suíte existente continuar verde e um teste de aceitação local no Windows demonstrar este fluxo completo:

1. configurar cache em outro volume;
2. iniciar com o cache vazio;
3. pesquisar uma série e navegar até um episódio;
4. preparar o episódio com progresso visível;
5. reproduzir MP4, trocar para uma dublagem M4A e selecionar uma legenda VTT;
6. reiniciar sem rede e reproduzir o mesmo episódio;
7. abrir o cache com uma `DirectorySource` e reproduzir os mesmos recursos;
8. apagar manualmente o MP4 e confirmar que ele volta a ser preparável.
