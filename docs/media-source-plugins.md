# Plugins de MediaSource

O WatchParty descobre plugins uma única vez no startup em `src/media_sources/plugins/`. Cada subpasta contém um `manifest.json`, um backend Python e, opcionalmente, um módulo ES para o painel do host.

```text
plugins/
  exemplo/
    __init__.py
    manifest.json
    backend.py
    host.mjs
```

Manifesto mínimo:

```json
{
  "type": "exemplo",
  "version": "1.0.0",
  "interface_version": 1,
  "backend": "backend:create_source",
  "host_module": "host.mjs",
  "python_dependencies": ["pacote_opcional"]
}
```

`create_source(source_id, options)` valida a configuração e devolve o Adapter que satisfaz a Interface `MediaSource`. Falhas de importação, versão, dependência ou configuração desabilitam somente o plugin ou instância afetada; o servidor continua iniciando e publica o diagnóstico em `/api/sources`.

O módulo ES exporta `mount(context)`. O contexto contém a Source selecionada, o slot DOM privado do plugin, navegação, atualização do catálogo, notificações e `request(action, options)`. `mount` devolve opcionalmente `cleanup`, `decorateCard` e `catalogRendered`. `cleanup` é chamado antes de trocar de Source.

As ações do backend ficam confinadas a:

```text
METHOD /host/<source_id>/<action>
```

O core resolve a instância, aplica a política de acesso do host, limita uploads e encaminha a ação opaca para `handle_host_action`. Cache, jobs, imagens, legendas e exportações continuam detalhes do plugin.

## Acesso administrativo

`allow_remote_host_admin` é `false` por padrão. Nesse estado, `/host`, módulos ES e ações exigem peer real e hostname local (`localhost`, `127.0.0.1` ou `::1`). O toggle **Permitir administração remota sem autenticação** só pode ser alterado pelo localhost e persiste em `save.json`. Quando ativado, qualquer cliente que alcance o servidor pode executar ações administrativas, deliberadamente sem autenticação.

## Lifecycle

- Adicionar, atualizar ou remover pasta exige restart; não há hot reload.
- O runtime não instala dependências automaticamente.
- Remover um plugin não apaga configuração, cache ou exportações.
- Dados específicos só voltam a ser administráveis ao reinstalar um plugin compatível.

## Contrato de segmentos de playback

`inspect(media_id)` devolve uma `OriginPresentation`; `materialize(media_id,
SegmentDemand)` devolve um `SegmentArtifact`. O artefato pode transportar:

```python
# Contrato anterior, ainda suportado:
SegmentArtifact(path, content_type, size, sha256)

# Conteúdo imutável em memória, sem arquivo temporário:
SegmentArtifact.from_bytes(data, content_type)
```

Exatamente um dos campos `path` e `data` deve estar presente. Consumidores usam
`await artifact.read_bytes()`; nunca devem presumir que `path` existe. Bytes
permanecem válidos enquanto o consumidor guardar a referência, mesmo se o plugin
remover a entrada do cache. O core não persiste artefatos em memória em disco.
`SegmentStore.publish` continua disponível para plugins que escolham persistir
seus próprios artefatos. Essa adição mantém `interface_version: 1` e os plugins
existentes que retornam arquivos continuam funcionando.

`locate(media_id, demand)` é opcional e deve retornar o artefato pronto ou `None`.
Prioridade não faz parte da identidade de um segmento: o core compartilha o
trabalho por origem/revisão, mídia, faixa, representação e segmento. Nenhum estado
de uma origem deve ser compartilhado acidentalmente com outra origem.

Os hooks assíncronos opcionais `release(media_id)` e `aclose()` encerram produtores
ao trocar de seleção e ao desligar o servidor, respectivamente. Plugins antigos
podem omiti-los. `release` pode preservar o cache; não deve apagar o arquivo original.

## Reprodução local em RAM

O plugin `directory` apenas lê a biblioteca durante a reprodução. FFprobe lê os
metadados; FFmpeg entrega MP4 fragmentado pelo stdout. Nenhum segmento, manifesto
ou arquivo temporário de conversão é escrito no disco. Geração/upload de capas
continua sendo uma ação administrativa explícita que escreve em `.previews`.

Opções de `directory`:

```json
{
  "path": "D:/Series e Filmes",
  "ffmpeg_path": "ffmpeg.exe",
  "transcode_profile": "chrome-h264-aac",
  "hardware_acceleration": "auto",
  "memory_cache_bytes": 268435456
}
```

- `memory_cache_bytes`: limite de **bytes de segmentos retidos**, por instância da
  origem, compartilhado por todos os espectadores. Padrão: 256 MiB. Zero desativa
  retenção; segmentos ainda são entregues por memória. Entradas menos usadas são
  descartadas; um segmento maior que o limite é entregue sem ficar no cache.
- O limite não inclui processos FFmpeg, metadados, pipes, um fragmento em produção
  ou respostas HTTP em andamento. Não é um teto de RAM do processo ou do sistema.
- A produção usa até dois processos por instância (normalmente vídeo e áudio),
  adianta até dois segmentos além do solicitado e aplica backpressure no pipe.
  Após 15 segundos sem novas demandas além dessa janela, encerra o produtor.
- Trechos consecutivos reutilizam o mesmo FFmpeg. Saltos/retornos para trechos
  ausentes na RAM abrem uma nova sequência; os timestamps permanecem absolutos.
- Vídeo H.264 de 8 bits, 4:2:0, em perfil suportado, usa stream copy com segmentos
  delimitados pelos keyframes originais. AAC-LC mono/estéreo a 44,1/48 kHz também
  é copiado. Outras faixas são convertidas individualmente para H.264/AAC.
- `auto` testa codificação real antes de selecionar AMF, NVENC ou QSV disponíveis
  na plataforma. Tenta decodificação acelerada e, se necessário, decodificação
  por software. Sem encoder de hardware utilizável, usa libx264. `software` força
  libx264. Falhas após iniciar uma apresentação são reportadas, sem trocar
  silenciosamente o codec de segmentos que já usam uma inicialização entregue.
- Cache antigo em `.watchparty/<source_id>/playback` não é lido, escrito nem
  apagado automaticamente. Pode ser removido manualmente para recuperar espaço.

Para verificar reprodução e seeks sem carregar configurações privadas do servidor:
`python tools/diagnose_directory_playback.py --root DIRETORIO --media CAMINHO_RELATIVO`.
O diagnóstico escuta somente em `127.0.0.1:8769` e mostra uso do cache e erros do player.
- Jobs pertencem à instância e vivem apenas durante o processo atual.
