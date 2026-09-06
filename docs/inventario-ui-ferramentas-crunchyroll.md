# Inventário funcional da UI — Ferramentas do Crunchyroll

## Objetivo deste documento

Este documento descreve o conteúdo, as funcionalidades, os estados e os dados atualmente expostos pelas interfaces de administração do plugin Crunchyroll no Painel do Host. Ele deve ser usado como briefing funcional para redesenhar a interface sem perder capacidades existentes.

O inventário foi levantado da implementação atual em:

- `files/host.html` e `files/host.js`: estrutura e comportamento dos modais;
- `src/media_sources/plugins/crunchyroll/host.mjs`: conteúdo específico do Crunchyroll;
- `src/media_sources/plugins/crunchyroll/source.py`, `cache.py` e `jobs.py`: dados e operações disponíveis no backend.

Há duas interfaces:

1. **Ferramentas — Crunchyroll**: administração global do plugin e do cache.
2. **Inspetor de entidade**: informações e ações de uma série, temporada, episódio ou filme selecionado.

---

## 1. Comportamento comum dos modais

- Modal centralizado sobre um overlay escuro.
- Largura atual: até `640px` ou `92vw`.
- Altura máxima atual: `88vh`, com rolagem apenas no corpo.
- Pode ser fechado por:
  - botão `×`;
  - tecla `Esc`;
  - clique no overlay fora do painel.
- Enquanto o conteúdo assíncrono é montado, o corpo mostra **“Carregando...”**.
- Erros de montagem aparecem no próprio corpo:
  - Ferramentas: mensagem do erro ou **“Extensão indisponível.”**;
  - Inspetor: mensagem do erro ou **“Inspetor indisponível.”**.
- Sucessos e erros de ações são mostrados fora do modal, no aviso global do Painel do Host, que desaparece após 4 segundos.
- Ao fechar, o conteúdo específico do plugin é desmontado e o polling de jobs é cancelado.
- O modal de Ferramentas só existe para origens que declaram a capacidade `tools`.

---

## 2. Modal global “Ferramentas — Crunchyroll”

### 2.1 Cabeçalho e introdução

- Título: **“Ferramentas — {nome da origem}”**; no caso mostrado, **“Ferramentas — Crunchyroll”**.
- Texto introdutório: **“Cache, downloads, legendas e exportações pertencem somente a este plugin.”**

Esse texto comunica que arquivos, cache e trabalhos aqui administrados não são compartilhados com outras origens de mídia.

### 2.2 Resumo global de armazenamento

Formato exibido:

`Armazenamento: {bytes em cache} · {quantidade de mídias} mídia(s) · {quantidade de exportações}`

Exemplo da captura:

`Armazenamento: 1.41 GiB · 9 mídia(s) · 0 exportação(ões)`

Dados disponíveis:

| Dado | Significado | Formatação atual |
|---|---|---|
| `cached_bytes` | Soma do tamanho dos segmentos em cache | B, KiB, MiB, GiB ou TiB, com duas casas após KiB |
| `media_count` | Número de mídias presentes no inventário do cache | Inteiro |
| `export_count` | Soma dos registros de MP4 exportados | Inteiro |

### 2.3 Seletor de mídia

- Um `select` ocupa toda a largura.
- Reúne:
  - mídias já conhecidas pelo inventário local;
  - itens reproduzíveis presentes na página atual do catálogo, mesmo que ainda não tenham cache.
- Cada opção mostra o **título** e usa internamente o **ID da mídia**.
- Ao atualizar a lista, tenta preservar a seleção anterior.
- Ao trocar a mídia:
  - o resumo individual é atualizado;
  - as faixas carregadas anteriormente são descartadas;
  - volta a ser exibido o estado inicial que pede o carregamento das faixas.

### 2.4 Resumo da mídia selecionada

Quando a mídia já está indexada:

`{estado} · {cobertura}% indexado · {bytes em cache} · {quantidade de exportações}`

Exemplo da captura:

`partial · 9% indexado · 332.63 MiB · 0 exportação(ões)`

Quando ainda não existe no inventário:

**“A mídia ainda não possui segmentos indexados.”**

Dados disponíveis por mídia:

| Dado | Significado |
|---|---|
| `media_id` | Identificador interno da mídia |
| `title` | Título conhecido localmente |
| `state` | Estado calculado: `empty`, `partial`, `offline` ou `exported` |
| `coverage` | Proporção de segmentos armazenados sobre o plano total da mídia |
| `cached_count` | Quantidade de segmentos armazenados |
| `cached_bytes` | Espaço ocupado pelos segmentos |
| `exports` | Lista de exportações registradas |
| `duration` | Duração da mídia |
| `revision` | Revisão da apresentação |
| `canonical_representation` | Representação de vídeo canônica |
| `updated_at` | Momento da última atualização do registro |
| `tracks` | Faixas e representações, incluindo cobertura individual |

Regras dos estados:

- `empty`: nenhum segmento em cache;
- `partial`: há segmentos, mas vídeo canônico e ao menos um áudio ainda não estão completos;
- `offline`: vídeo canônico e ao menos um áudio estão completos;
- `exported`: existe uma exportação registrada cujo arquivo e hash ainda são válidos.

### 2.5 Ações principais

#### Atualizar inventário

- Recarrega inventário, armazenamento, jobs e preferências do backend.
- Repopula o seletor de mídia e recalcula os resumos.
- Não baixa conteúdo remoto.
- Em caso de falha, mostra a mensagem do backend no aviso global.

#### Carregar faixas

- Consulta a apresentação da mídia selecionada.
- Revela a seleção detalhada de vídeo, áudio e legendas.
- Em caso de falha, mostra a mensagem do backend no aviso global.

#### Atualizar catálogo

- Apaga o cache local de metadados do catálogo.
- Atualiza novamente a visão atual do explorador.
- Mensagem de sucesso: **“Catálogo atualizado.”**
- Não equivale a atualizar o inventário de segmentos.

#### Relatório de falhas

- Consulta falhas dos jobs da execução atual.
- A UI atual não lista detalhes; mostra somente:
  - **“{N} falha(s) registradas.”**; ou
  - **“Nenhuma falha registrada nesta execução.”**
- O backend já fornece, por job:
  - ID;
  - tipo do job;
  - estado;
  - lista de falhas.
- Cada falha contém:
  - `media_id`;
  - `stage` (etapa);
  - `attempt` (tentativa);
  - `fallback`;
  - `error` (limitado a 500 caracteres).

### 2.6 Seleção de faixas

Estado inicial: **“Carregue as faixas da mídia selecionada.”**

Depois de carregar, cada faixa aparece em um `fieldset` com legenda:

`{tipo da faixa} · {rótulo, idioma ou ID}`

Tipos e controles:

| Tipo (`kind`) | Controle | Seleção inicial |
|---|---|---|
| `video` | Radio button; somente uma representação | Representação canônica |
| `audio` | Checkbox | Idiomas configurados nas preferências; aceita `*` como curinga |
| `text` | Checkbox | Idiomas configurados nas preferências; aceita `*` como curinga |

Cada representação exibe:

- `{altura}p`, quando possui altura de vídeo; ou
- `{bitrate arredondado} kbps`, nos demais casos.

Dados disponíveis na apresentação:

- ID, título, duração e revisão da mídia;
- representação de vídeo canônica;
- por faixa: ID, tipo, idioma, rótulo, indicador de faixa padrão e representações;
- por representação: ID, largura, altura, bitrate, codecs, MIME type, inicialização e segmentos.

Payload formado pela seleção:

- `media_id`;
- `video_representation`;
- `audio_tracks[]`;
- `subtitle_tracks[]`.

### 2.7 Operações da mídia selecionada

#### Iniciar download

- Garante que as faixas estejam carregadas.
- Cria um job `download` com a seleção atual.
- Faz download dos segmentos ausentes para o cache do plugin.
- Mensagem imediata: **“{tipo do job} iniciado.”**
- Passa a acompanhar os jobs uma vez por segundo.

#### Salvar como MP4

- Cria um job `export-mp4` com a seleção atual.
- Apesar do nome, a implementação também completa segmentos ausentes antes de exportar.
- O arquivo é exportado para a pasta configurada, preservando até dois níveis da hierarquia do catálogo.
- Se já existir um arquivo com o mesmo nome, cria `Nome (2).mp4`, `Nome (3).mp4` etc.
- Vídeo e áudio são copiados sem recodificação; legendas são incorporadas como `mov_text` e também copiadas como arquivos sidecar.

### 2.8 Adicionar legenda

Campos:

1. Seletor de arquivo, limitado na UI a `.ass`, `.srt` e `.vtt`.
2. Idioma obrigatório, placeholder **“Idioma, ex.: pt-BR”**.
3. Rótulo opcional, placeholder **“Rótulo opcional”**.
4. Botão **“Enviar legenda”**.

Validações e comportamento:

- mídia, arquivo e idioma são obrigatórios;
- formatos aceitos: ASS, SRT e WebVTT;
- limite do arquivo: 16 MiB;
- se o rótulo estiver vazio, o idioma é usado como rótulo;
- ASS e SRT são convertidos para WebVTT, preservando também o original;
- após o envio, as faixas são recarregadas;
- mensagem de sucesso: **“Legenda adicionada.”**;
- validação local incompleta mostra **“Selecione mídia, arquivo e idioma.”**.

Dados retornados pelo upload: ID do anexo, idioma e rótulo.

### 2.9 Limpeza do cache

Título: **“Limpeza do cache”**.

Controles:

- seletor de modo;
- campo contextual com placeholder **“Altura (480) ou dias (30)”**;
- botão **“Simular limpeza”**;
- botão **“Executar limpeza”**, inicialmente desabilitado;
- linha de resultado da simulação.

Modos disponíveis:

| Valor | Rótulo atual | Regra |
|---|---|---|
| `exported` | Mídias com MP4 exportado | Segmentos das mídias que possuem exportação válida |
| `quality` | Qualidade de vídeo | Segmentos cuja representação tem exatamente a altura informada |
| `partial` | Parciais antigas | Segmentos de mídias incompletas sem acesso há N dias; padrão de 30 dias |
| `media` | Mídia selecionada | Segmentos da mídia escolhida no seletor |
| `collection` | Série/temporada atual | Segmentos descendentes do contexto atual do catálogo |
| `orphans` | Órfãos | Arquivos sem registro correspondente no índice |
| `all` | Todo o cache de segmentos | Todos os segmentos gerenciados |

Simulação:

- não remove arquivos;
- retorna e mostra **“{N} arquivo(s), {tamanho}, {N} mídia(s).”**;
- habilita a execução somente quando encontra ao menos um arquivo;
- arquivos em uso por reprodução/exportação são excluídos da seleção.

Execução:

- pede confirmação nativa do navegador: **“Executar a limpeza simulada? Arquivos de cache removidos terão de ser baixados novamente.”**;
- retorna arquivos removidos, ignorados e bytes recuperados;
- mostra **“{N} arquivo(s) removido(s), {tamanho} recuperados.”**;
- desabilita novamente o botão e atualiza o inventário.

Observação funcional: alterar o modo ou valor depois de uma simulação não invalida visualmente o resultado nem desabilita automaticamente o botão de execução. A execução recalcula o payload atual, portanto pode não corresponder à simulação visível.

### 2.10 Preferências padrão

Título: **“Preferências padrão”**.

Texto auxiliar: **“Qualidade, áudio e legendas são preferências para novos jobs.”**

Campos:

| Campo | Placeholder | Valor |
|---|---|---|
| Qualidade máxima de vídeo | “Qualidade máxima” | Texto livre (`video_quality`) |
| Idiomas de áudio | “Áudios (separados por vírgula)” | Lista convertida de/para CSV |
| Idiomas de legenda | “Legendas (separadas por vírgula)” | Lista convertida de/para CSV |

- Botão: **“Salvar preferências”**.
- Espaços são removidos das pontas e itens vazios são descartados.
- Mensagem de sucesso: **“Preferências salvas.”**
- O backend também suporta `audio_quality`, mas a UI atual não o mostra.
- As preferências determinam a seleção inicial das faixas em novos jobs; `*` seleciona qualquer idioma.

### 2.11 Jobs desta execução

Título: **“Jobs desta execução”**.

Quando vazio: **“Nenhum job nesta execução.”**

Cada job é mostrado atualmente como uma única linha:

`{tipo}: {estado} · {concluídos}/{total} · {mensagem opcional} · {erro opcional}`

Dados disponíveis:

| Dado | Significado |
|---|---|
| `id` | Identificador transitório do job |
| `kind` | Tipo da operação |
| `state` | Estado atual |
| `completed` / `total` | Progresso numérico |
| `message` | Etapa ou descrição de progresso |
| `error` | Erro geral, até 500 caracteres |
| `created_at` / `updated_at` | Timestamps |
| `failures[]` | Falhas individuais, principalmente em lote |

Estados possíveis na implementação:

- `queued`;
- `running`;
- `paused`;
- `completed`;
- `completed_with_failures`;
- `failed`;
- `cancelled`.

Ações por estado:

- `queued` ou `running`: **Pausar** e **Cancelar**;
- `paused`: **Retomar** e **Cancelar**;
- estados finais: sem botões.

Enquanto houver job ativo, a lista é consultada a cada segundo. Ao terminar o último job ativo, o inventário é atualizado.

Os jobs são apenas da execução atual do processo; não há histórico persistente apresentado nessa tela.

---

## 3. Inspetor de entidade

O inspetor abre ao clicar no título de um card do Crunchyroll.

### 3.1 Cabeçalho gerenciado pelo host

- Título: título da entidade.
- Contexto: **“{tipo da entidade} · {nome da origem}”**.
- Botão `×` para fechar.

Exemplos das capturas:

- **“Frieren e a Jornada para o Além”** / `series · Crunchyroll`;
- **“O fim da aventura”** / `episode · Crunchyroll`.

### 3.2 Favorito

- Checkbox **“Favorito”**, sempre renderizado pelo host.
- Reflete o estado `favorited` da entidade.
- A alteração é otimista e sincronizada com `/api/favorites`.
- Em sucesso, mostra:
  - **“Adicionado aos favoritos.”**; ou
  - **“Removido dos favoritos.”**
- Em erro, restaura o estado anterior e mostra a mensagem recebida.

### 3.3 Bloco do plugin

Título interno:

`{título} · {entity_kind, media_kind ou “mídia”}`

Durante a consulta: **“Carregando disponibilidade…”**

Ações exibidas em todos os tipos:

1. **Baixar para cache**;
2. **Salvar como MP4**;
3. **Baixar e salvar como MP4**.

O significado e a disponibilidade mudam conforme o tipo da entidade.

### 3.4 Episódio ou filme (`entry_type = playable`)

Linha de status:

`{estado ou “disponível remotamente”} · {cobertura}% em cache`

Exemplo da captura:

`partial · 5% em cache`

Estados mostrados:

- **disponível remotamente**: não há registro no inventário;
- `empty`;
- `partial`;
- `offline`;
- `exported`.

Regras dos botões:

| Ação | Disponibilidade atual | Operação |
|---|---|---|
| Baixar para cache | Sempre habilitada após carregar os dados | `download` |
| Salvar como MP4 | Somente em `offline` ou `exported` | `export-mp4` |
| Baixar e salvar como MP4 | Sempre habilitada após carregar os dados | `download-export` |

Seleção usada pelo inspetor, sem controles visíveis:

- representação de vídeo canônica;
- todas as faixas de áudio marcadas como padrão;
- nenhuma legenda.

Ao iniciar uma ação, mostra **“{tipo do job} iniciado.”** no aviso global. O inspetor não exibe progresso nem atualiza seu status automaticamente depois do início.

### 3.5 Série ou temporada (`entry_type != playable`)

Linha de status:

`Cache agregado · {completos} completo(s) · {parciais} parcial(is) · {episódios} episódio(s)`

Exemplo da captura:

`Cache agregado · 0 completo(s) · 8 parcial(is) · 9 episódio(s)`

Regras:

- completo: mídia em estado `offline` ou `exported`;
- parcial: mídia em estado `partial`;
- todas as três ações aparecem, mas ficam desabilitadas;
- não há lista de episódios, seleção em lote, espaço ocupado ou jobs relacionados na UI atual.

Limitação importante da implementação atual: o agregado filtra todos os IDs iniciados por `episode:` no inventário, sem restringi-los aos descendentes da série/temporada aberta. Portanto, os números podem representar o cache global de episódios, e não a entidade inspecionada.

### 3.6 Estado de erro/offline

Se falhar a consulta de apresentação ou inventário, a linha de status recebe:

- a mensagem específica do erro; ou
- **“Disponibilidade desatualizada (offline).”**

Os botões não são explicitamente desabilitados nesse caminho. Como os handlers só são associados depois de uma consulta bem-sucedida, podem parecer habilitados sem executar ação alguma.

---

## 4. Capacidades existentes no backend ainda não expostas pela UI

Estas capacidades podem ser consideradas pelo redesign, mas devem ser marcadas como expansão de interface, não como conteúdo visual atual:

- download em lote por uma lista de `media_ids` (`batch-download`);
- download + exportação em lote (`batch-download-export`);
- falhas detalhadas por mídia, etapa, tentativa e fallback;
- consulta individual de um job por ID;
- `audio_quality` nas preferências;
- detalhes completos das exportações: ID, caminho, tamanho, SHA-256 e data de criação;
- detalhes de cache por faixa e representação: segmentos armazenados, bytes e cobertura;
- `skipped` no resultado da limpeza;
- duração, codecs, MIME type, largura, bitrate e contagem de segmentos das representações.

---

## 5. Inconsistências e riscos que o redesign deve resolver

1. **Arquitetura de informação:** todas as funções globais formam uma coluna longa e sem agrupamento visual; conteúdo importante fica abaixo da dobra.
2. **Idioma técnico:** estados e tipos aparecem crus em inglês (`partial`, `offline`, `exported`, `download`, `export-mp4`, `series`, `episode`).
3. **Ações ambíguas:** em Ferramentas, **Salvar como MP4** também baixa ausências; no Inspetor, a mesma ação exige cache completo, enquanto existe outra ação chamada **Baixar e salvar como MP4**.
4. **Feedback fora de contexto:** mensagens de sucesso/erro aparecem no topo da página, possivelmente encobertas pelo modal e longe do controle acionado.
5. **Carregamento parcial:** não há estado de loading individual nos botões nem bloqueio contra cliques repetidos.
6. **Relatório insuficiente:** o botão de relatório reduz todos os dados disponíveis a uma contagem textual.
7. **Jobs pouco escaneáveis:** progresso, tipo, estado, mensagem e erro são concatenados em texto corrido; não há barra de progresso nem agrupamento.
8. **Limpeza arriscada:** usa `confirm()` nativo, o campo “altura ou dias” permanece visível para modos que não precisam dele e a simulação pode ficar obsoleta após alterar filtros.
9. **Preferências sem opções guiadas:** qualidade e idiomas são texto livre, sem descoberta de valores aceitos, validação visível ou explicação do curinga `*`.
10. **Faixas muito técnicas:** `kind`, idioma/ID e representações são mostrados quase diretamente; áudio e legenda usam checkboxes, mas não deixam clara a combinação que será exportada.
11. **Agregado incorreto ou enganoso:** série/temporada pode mostrar números globais de episódios.
12. **Ações de coleção falsas:** botões em série/temporada são visíveis, porém permanentemente desabilitados e sem explicação.
13. **Erro com aparência acionável:** no Inspetor, falhas de carregamento podem deixar botões visualmente habilitados, embora sem handlers.
14. **Atualização do estado:** o Inspetor não acompanha o job iniciado nem atualiza cobertura/estado ao concluí-lo.
15. **Acessibilidade:** os grupos de controles têm estrutura semântica básica, mas faltam descrições de ajuda, estados de carregamento anunciados, foco inicial/restaurado e explicação textual para botões desabilitados.

---

## 6. Requisitos mínimos para uma nova interface preservar

- Separar claramente escopo **global** (armazenamento, catálogo, limpeza, preferências, jobs e falhas) de escopo **da mídia** (faixas, download, exportação e legenda).
- Manter seleção explícita de uma representação de vídeo e múltiplos áudios/legendas no modal global.
- Manter os sete modos de limpeza e a etapa obrigatória de simulação antes da execução.
- Mostrar armazenamento global e estado/cobertura/tamanho/exportações por mídia.
- Preservar upload de ASS, SRT e VTT com idioma obrigatório e rótulo opcional.
- Preservar criação, pausa, retomada e cancelamento de jobs, além de progresso e erros.
- Preservar favorito no Inspetor.
- Diferenciar de forma compreensível: apenas baixar, apenas exportar o que já está completo e baixar + exportar.
- Oferecer estados claros de carregamento, vazio, sucesso, erro, indisponibilidade e ação desabilitada.
- Evitar ações destrutivas sem resumo do impacto e confirmação contextual.
- Traduzir estados/tipos para linguagem de produto, mantendo os valores técnicos apenas como metadados secundários quando úteis.

---

## 7. Glossário funcional sugerido para o design

| Termo técnico atual | Significado para o usuário |
|---|---|
| Inventário | Índice local do que já foi descoberto, baixado ou exportado |
| Catálogo | Metadados navegáveis vindos do Crunchyroll |
| Apresentação | Conjunto disponível de vídeo, áudios, legendas e qualidades de uma mídia |
| Segmento | Pequena parte de uma faixa armazenada no cache |
| Cache parcial | Apenas parte dos segmentos necessários está localmente disponível |
| Disponível offline | Vídeo canônico e ao menos um áudio estão completos no cache |
| Exportado | Há um MP4 válido registrado para a mídia |
| Job | Operação assíncrona de download, exportação ou lote |
| Órfão | Arquivo físico do cache que não possui registro no índice |
| Representação | Variante de qualidade/bitrate de uma faixa |

