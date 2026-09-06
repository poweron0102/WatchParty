# Plano de implementação — Redesign da UI do plugin Crunchyroll

## Objetivo

Reorganizar os dois modais existentes (**Ferramentas — Crunchyroll** e **Inspetor de entidade**) para resolver os 15 riscos listados no inventário funcional, traduzir a linguagem técnica em produto, e já expor as capacidades de backend hoje ausentes da UI (download em lote, falhas detalhadas, detalhes de exportação/cache, `audio_quality`).

---

## 1. Princípios de design

1. **Tradução antes de exposição.** Nenhum valor técnico cru (`partial`, `series`, `export-mp4`) aparece como texto principal — sempre como rótulo traduzido, com o valor técnico disponível como metadado secundário (tooltip ou texto pequeno).
2. **Estado sempre visível, nunca surpresa.** Todo controle mostra seu estado (carregando, vazio, erro, desabilitado com motivo) sem exigir uma ação para descobrir.
3. **Feedback no ponto de origem.** A confirmação de uma ação aparece perto do controle que a disparou, não apenas em um aviso global distante.
4. **Uma ação, uma decisão.** Onde hoje existem botões concorrentes com semântica parecida (baixar / exportar / baixar+exportar), o usuário escolhe uma intenção clara, não decifra três rótulos.
5. **Nada de ação destrutiva sem prever o impacto.** Toda limpeza mostra volume afetado antes de confirmar, e a confirmação vive dentro do modal.

---

## 2. Sistema de design proposto (tokens)

### Cores (tema escuro, neutro, com acentos semânticos)

Usar o presente

### Tipografia

Usar o presente

### Componentes reutilizáveis

- **Badge de estado**: pílula colorida (cor por `--state-*`) com rótulo traduzido; tooltip mostra o valor técnico original.
- **Cartão de mídia**: título, badge de estado, barra de cobertura, linha de metadados (tamanho, exportações), menu de ações.
- **Barra de progresso**: usada em cobertura de cache e em jobs; preenchimento anima de 0 até o valor atual.
- **Chip de idioma**: chip removível com nome legível do idioma; um chip especial "Todos os idiomas" representa o curinga `*`.
- **Painel de confirmação inline**: substitui `confirm()` nativo; aparece expandido dentro do próprio modal, com resumo do impacto e dois botões (cancelar / confirmar destrutivo).
- **Toast de ação com escopo**: pequeno indicador de sucesso/erro ancorado ao botão que disparou a ação (2–3s), complementar ao aviso global do host.
- **Tooltip de motivo**: qualquer botão desabilitado tem `aria-describedby` explicando por que está desabilitado, visível também ao passar o mouse/focar.

---

## 3. Nova arquitetura de informação — Modal "Ferramentas"

Trocar a coluna única por **abas dentro do modal**, mantendo o cabeçalho fixo:

```
[Ferramentas — Crunchyroll]                                   [×]
Cache, downloads, legendas e exportações pertencem só a este plugin.
────────────────────────────────────────────────────────────────
[ Visão geral ] [ Mídia ] [ Manutenção ] [ Atividade ]
────────────────────────────────────────────────────────────────
```

### Aba "Visão geral"
- Cartão de armazenamento global (bytes em cache, mídias, exportações) com ícones, não texto corrido.
- Ações rápidas em toolbar de ícones com tooltip: Atualizar inventário · Atualizar catálogo · Ver relatório de falhas.
- Lista compacta das mídias com cache, cada uma como cartão de mídia clicável, que leva para a aba "Mídia" já com aquela mídia selecionada.

### Aba "Mídia"
- Seletor combobox com busca (substitui o `<select>` simples), cada opção com badge de estado.
- Cartão de resumo da mídia selecionada (estado, cobertura, tamanho, exportações — expansível para ver detalhe por faixa/representação, hoje ausente da UI).
- Botão "Carregar faixas" some assim que as faixas já estiverem carregadas; ao trocar a mídia, o cartão de faixas recolhe automaticamente para o estado vazio ("Carregue as faixas desta mídia").
- Seleção de faixas:
  - Vídeo: controle segmentado por representação (`1080p`, `720p`, `540 kbps`, etc.).
  - Áudio / Legenda: chips de idioma com nome legível; chip "Todos os idiomas" para `*`.
- Bloco de ação unificado — ver seção 5 (nova semântica de ações).
- Bloco de legendas (upload) — ver seção 6.

### Aba "Manutenção"
- **Limpeza do cache** como wizard de 2 passos — ver seção 7.
- **Preferências padrão** com chips de idioma + campo `audio_quality` (hoje ausente da UI) + campo de qualidade de vídeo com valores sugeridos pelo backend, se disponíveis, em vez de texto livre sem validação.

### Aba "Atividade"
- **Jobs desta execução** como lista de cartões com progresso — ver seção 8.
- **Relatório de falhas** expandido em tabela — ver seção 8.
- Suporte a **download em lote** e **download+exportação em lote** (capacidades de backend hoje não expostas) — ver seção 9.

---

## 4. Cartão de mídia (componente central)

```
┌──────────────────────────────────────────────┐
│ ● Frieren e a Jornada — Ep. 12                │
│ [Parcial]  ▓▓▓▓░░░░░░ 9%   332.63 MiB   0 exp.│
│                                     [ ⋯ ações ]│
└──────────────────────────────────────────────┘
```
- Badge de estado traduzido (`Vazio`, `Parcial`, `Disponível offline`, `Exportado`).
- Barra de cobertura com percentual.
- Tamanho em cache e contagem de exportações como texto secundário.
- Menu de ações (⋯) leva para o bloco de ação unificado com esta mídia pré-selecionada — usado tanto na aba "Visão geral" quanto no futuro seletor em lote.

---

## 5. Nova semântica das ações de download/exportação

Problema mapeado (risco 3 do inventário): "Salvar como MP4" também baixa o que falta; "Baixar e salvar como MP4" existe em paralelo; a mesma ação tem regras diferentes em Ferramentas e no Inspetor.

**Solução: uma única pergunta de intenção, com resultado determinístico.**

```
O que você quer fazer com esta mídia?

○ Só baixar para o cache local
   Guarda os segmentos de vídeo/áudio/legenda selecionados no dispositivo.

○ Só exportar o que já está completo
   Gera um arquivo MP4 a partir do que já está em cache.
   (desabilitado com tooltip "Ainda faltam segmentos" quando não está offline/exportado)

○ Baixar e depois exportar
   Completa o cache que faltar e gera o MP4 na sequência.

[ Iniciar ]
```

- As três opções mapeiam exatamente para `download`, `export-mp4` (sem download automático de ausências — isso é uma decisão de produto a validar, ver observação abaixo) e `download-export`.
- **Observação para validar com o time de backend:** hoje `export-mp4` completa ausências "por baixo dos panos" apesar do nome. Recomendo que o backend pare de fazer isso silenciosamente e que a opção "Só exportar" realmente falhe com uma mensagem clara ("Faltam segmentos, use 'Baixar e depois exportar'") — ou, se o comportamento atual for intencional, a UI deve dizer isso explicitamente na descrição da opção, para não haver ambiguidade nenhuma.
- No **Inspetor**, as mesmas três opções aparecem como botões diretos (contexto de mídia única, sem seleção de faixas visível), com a mesma tradução e os mesmos tooltips de motivo quando desabilitado.

---

## 6. Upload de legenda

- Área de arrastar-e-soltar + botão "Escolher arquivo", aceitando apenas `.ass`, `.srt`, `.vtt` (validação visível: "Formatos aceitos: ASS, SRT, VTT — até 16 MB").
- Campo de idioma com autocomplete de idiomas comuns (não texto livre puro), mantendo liberdade de digitar um código não listado.
- Rótulo opcional com placeholder indicando que o idioma será usado como rótulo se vazio.
- Erros de validação aparecem inline embaixo do campo relevante, não só como mensagem genérica.

---

## 7. Limpeza do cache — wizard de 2 passos

**Passo 1 — Escolher o quê limpar**
- Seletor de modo com descrição de uma linha por opção (ex.: "Órfãos — arquivos sem registro no índice").
- Campo contextual ("Altura (480) ou dias (30)") só aparece para os modos que precisam dele (`quality`, `partial`); escondido nos demais — resolve o risco 8.
- Botão "Simular limpeza".

**Passo 2 — Revisar e confirmar**
- Cartão de resultado da simulação: "{N} arquivos · {tamanho} · {N} mídias".
- Se o usuário alterar modo/valor depois de simular, o cartão fica visualmente marcado como **obsoleto** ("Resultado desatualizado — simule novamente") e o botão de execução é bloqueado até nova simulação — resolve a falha crítica do risco 8.
- Confirmação **dentro do modal** (painel de confirmação inline), substituindo o `confirm()` nativo, repetindo o resumo do impacto e um aviso claro de que os arquivos removidos precisarão ser baixados novamente.
- Resultado da execução mostrado no mesmo cartão: "{N} removidos · {tamanho} recuperados" + contagem de `skipped` (arquivos em uso, hoje não exposta na UI, mas disponível no backend).

---

## 8. Jobs e falhas

### Cartão de job

```
┌──────────────────────────────────────────────┐
│ ⬇ Download · Frieren Ep. 12                   │
│ ▓▓▓▓▓▓░░░░  62%   Em execução                 │
│                                [Pausar] [Cancelar] │
└──────────────────────────────────────────────┘
```
- Ícone por tipo de job (download, exportação, lote).
- Barra de progresso real (`completed`/`total`), não só texto.
- Badge de estado traduzido (`Na fila`, `Em execução`, `Pausado`, `Concluído`, `Concluído com falhas`, `Falhou`, `Cancelado`).
- Ações contextuais por estado, como já definido no inventário (pausar/cancelar, retomar/cancelar, nenhuma em estados finais).
- Jobs com falha mostram um contador de falhas clicável, que expande a tabela de falhas abaixo do próprio cartão.

### Tabela de falhas (expandida por job, ou na aba Atividade)

| Mídia | Etapa | Tentativa | Fallback usado | Erro |
|---|---|---|---|---|
| ... | ... | ... | Sim/Não | (truncado a 500 caracteres, com "ver completo") |

Isso substitui o atual "{N} falha(s) registradas." por dados realmente utilizáveis, que o backend já fornece.

---

## 9. Capacidades novas a expor (expansão de escopo já aprovada)

1. **Download em lote / download+exportação em lote** (`batch-download`, `batch-download-export`): adicionar seleção múltipla no cartão de mídia (checkbox em modo "seleção em lote", ativado por um botão na aba "Visão geral" ou na aba "Mídia"). Barra de ação flutuante aparece quando há itens selecionados: "3 mídias selecionadas — [Baixar em lote] [Baixar e exportar em lote]".
2. **Falhas detalhadas por job** — já cobertas na seção 8.
3. **`audio_quality` nas preferências** — novo campo na aba "Manutenção", ao lado de qualidade de vídeo.
4. **Detalhes completos de exportação** (ID, caminho, tamanho, SHA-256, data): exibidos ao expandir a contagem "0 exportação(ões)" no cartão de mídia, como uma lista de exportações com esses metadados.
5. **Detalhes de cache por faixa/representação** (segmentos, bytes, cobertura individual): exibidos ao expandir cada faixa no bloco de seleção — hoje só existe a cobertura agregada da mídia.
6. **`skipped` no resultado da limpeza** — já incluso na seção 7.
7. **Consulta individual de job por ID** — usada internamente para o polling do cartão expandido, sem necessidade de UI própria adicional além do que já foi descrito.

---

## 10. Inspetor de entidade

### Cabeçalho
- Ícone de estrela (toggle) para favorito, no canto do cabeçalho, em vez do checkbox "Favorito" — mais compacto e consistente com o padrão de "favoritar" em apps de mídia.
- Estado otimista mantido; toast inline junto ao ícone em caso de erro (com rollback visual).

### Episódio ou filme
- Linha de status como badge + barra de cobertura (mesmo componente do cartão de mídia).
- As três ações (baixar / salvar como MP4 / baixar e salvar) usam a mesma semântica unificada da seção 5, como botões diretos (sem seleção de faixas — a seleção implícita continua sendo canônico + áudios padrão + nenhuma legenda, mas isso passa a ser dito explicitamente em um texto pequeno abaixo dos botões: "Usa a faixa de vídeo padrão e os áudios marcados como padrão").
- Ao iniciar uma ação, o próprio Inspetor passa a exibir uma barra de progresso mini que faz polling do job (resolve o risco 14 — hoje ele não acompanha nada depois do início).

### Série ou temporada
- Linha de status mantém o agregado (completos/parciais/episódios), mas com uma ressalva a corrigir no backend: **o agregado deve filtrar apenas os descendentes reais da série/temporada aberta**, não todo o inventário global de episódios (risco 11 — bug funcional, não só de UI).
- As três ações somem, substituídas por uma nota curta: "Ações em lote para coleções ainda não disponíveis nesta tela" — evita botões mortos sem explicação (risco 12). Quando o item 9.1 (lote) for implementado, isso se torna o local natural para "Baixar todos os episódios parciais", por exemplo.

### Estado de erro/offline
- Quando a consulta falha, os botões ficam **explicitamente desabilitados** (não apenas sem handler), com tooltip "Não foi possível carregar a disponibilidade — tente novamente" e um botão de retry visível — resolve o risco 13.

---

## 11. Acessibilidade

- Regiões `aria-live="polite"` para mensagens de carregamento, sucesso e erro.
- Foco inicial no título do modal ao abrir; foco restaurado ao elemento que abriu o modal ao fechar.
- Todo botão desabilitado tem `aria-describedby` apontando para o motivo (tooltip visível também sem hover, via foco de teclado).
- Grupos de faixas (`fieldset`/`legend`) mantidos e complementados com `aria-label` explicando a seleção atual.
- Contraste mínimo AA para todos os tokens de cor de estado sobre `--bg-elevated`.

---

## 12. Mapeamento risco → solução

| # | Risco (inventário, seção 5) | Solução neste plano |
|---|---|---|
| 1 | Coluna longa sem agrupamento | Abas (seção 3) |
| 2 | Idioma técnico cru | Badges traduzidos + glossário aplicado (seção 2, 4) |
| 3 | Ações ambíguas de download/exportação | Semântica unificada de intenção (seção 5) |
| 4 | Feedback fora de contexto | Toast ancorado ao botão + aviso global complementar (seção 2) |
| 5 | Sem loading por botão | Estado de carregamento por botão, bloqueio contra clique repetido (implícito em todos os componentes) |
| 6 | Relatório de falhas insuficiente | Tabela de falhas detalhada (seção 8) |
| 7 | Jobs pouco escaneáveis | Cartão de job com barra de progresso (seção 8) |
| 8 | Limpeza arriscada | Wizard de 2 passos + invalidação automática + confirmação inline (seção 7) |
| 9 | Preferências sem opções guiadas | Chips com autocomplete, campo `audio_quality` (seção 3, 9) |
| 10 | Faixas muito técnicas | Chips de idioma legível, controle segmentado de vídeo (seção 3) |
| 11 | Agregado incorreto em série/temporada | Correção de filtro no backend (seção 10) |
| 12 | Ações de coleção falsas | Nota explicativa em vez de botão morto (seção 10) |
| 13 | Erro com aparência acionável | Desabilitação explícita + retry (seção 10) |
| 14 | Inspetor não acompanha job | Progresso inline com polling (seção 10) |
| 15 | Acessibilidade | Seção 11 |

---

## 13. Fases de implementação sugeridas

**Fase 1 — Fundamentos visuais e tradução**
- Tokens de cor/tipografia, componente de badge, cartão de mídia, tooltips de motivo.
- Tradução de todos os rótulos técnicos.

**Fase 2 — Reestruturação em abas do modal "Ferramentas"**
- Migrar conteúdo existente para Visão geral / Mídia / Manutenção / Atividade, sem mudar capacidades.
- Wizard de limpeza, cartões de job, tabela de falhas.

**Fase 3 — Nova semântica de ações + Inspetor**
- Bloco de ação unificado (download/exportar/ambos) nos dois modais.
- Progresso inline no Inspetor, correção de estados de erro/série.

**Fase 4 — Expansão de capacidades de backend**
- Seleção em lote + ações em lote.
- Detalhes de exportação e de cache por faixa/representação.
- Campo `audio_quality`, contagem `skipped` na limpeza.

**Fase 5 — Correções de backend acopladas à UI**
- Filtro correto do agregado de série/temporada.
- Decisão de produto sobre o comportamento silencioso de "Salvar como MP4" completando ausências.