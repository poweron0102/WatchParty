# Plano de design: Painel do Host

## Objetivo

Traduzir o contrato funcional descrito em `host-plugin-functional-plan.md` em uma estrutura visual concreta, sem redesenhar a identidade existente (Tailwind + variáveis CSS já em uso, paleta escura, `Inter`). Este documento cobre layout, componentes e estados — não define copy final nem ícones exatos.

## 1. Visão geral do layout

A página continua com duas colunas em telas largas (`grid-cols-1 lg:grid-cols-[minmax(280px,1fr)_2fr]` ou equivalente), mas o conteúdo da coluna direita muda de forma:

```
┌─────────────────────────────┬──────────────────────────────────────────────┐
│ Coluna esquerda (config)     │ Explorador de Mídia                           │
│  - Link de Convite           │  ┌────────────┬───────────────────────────┐  │
│  - Conexão WebRTC             │  │ Views      │ Breadcrumb (se aplicável) │  │
│  - Origem de Mídia            │  │ (sidebar)  │ Busca                     │  │
│  - Acesso administrativo      │  │            │ Grids (Vídeos / Pastas)   │  │
│  - Botão "Ferramentas ▸"      │  │            │                           │  │
└─────────────────────────────┴──┴────────────┴───────────────────────────┘
```

A coluna esquerda perde o card fixo "Ferramentas da origem" e ganha, no lugar, um botão simples (`Ferramentas da origem ▸`) que abre o modal de Ferramentas. Ele só aparece quando `source.host_module` existir e a extensão declarar a capacidade de ferramentas globais — mesma lógica condicional que hoje esconde/mostra `source-extension-card`.

## 2. Sidebar de views (dentro do Explorador de Mídia)

Lista vertical fixa à esquerda do explorador, largura ~180–200px, colapsável em mobile (vira um `select` ou uma faixa horizontal rolável abaixo de ~768px).

Ordem de exibição:

1. Views nativas do host, na ordem do plano: **Popular, Novidades, A-Z, Gêneros**.
2. **Histórico** e **Favoritos** — sempre presentes, independem do plugin.
3. Views declaradas pelo plugin (ex.: **Cache local** do Crunchyroll) aparecem depois, com um separador sutil (`border-t`) entre as nativas e as do plugin.

Cada item: rótulo + contador opcional (ex. "Favoritos · 12"), estado ativo com `bg-input` + borda esquerda `border-brand`. Trocar de view:

- Reseta busca e breadcrumb.
- Não fecha modais abertos, mas o Inspetor perde o contexto de entidade se a entidade selecionada não pertencer mais à view.

### Comportamento por tipo de view

| View | Breadcrumb | Grids | Ordenação |
|---|---|---|---|
| Popular / Novidades | Não (lista plana) ou sim, se o plugin paginar por categoria | Vídeos + Pastas conforme o item | Definida pelo plugin, cursor próprio |
| A-Z / Gêneros | Sim, se navegável hierarquicamente | Vídeos + Pastas | Alfabética / por gênero |
| Histórico | Não | Lista única (sem separar por tipo) | `last_played_at` desc |
| Favoritos | Não | Lista única | `favorited_at` desc |
| Cache local (Crunchyroll) | Sim, por agrupamento (`Sem agrupamento` incluso) | Vídeos + Pastas | Último acesso agregado |

Views sem breadcrumb escondem a `<nav>` de breadcrumbs por completo (não deixam vazia).

## 3. Cards de entidade

Mantém a estrutura visual atual (`media-item`, imagem 16:9 ou 2:3, `type-indicator`, `file-name`). Duas mudanças:

- **Duas zonas clicáveis**: o elemento deixa de ser um único `<button>` e passa a ter dois alvos de clique — a imagem/corpo (ação padrão: navegar ou definir mídia) e o `file-name` (título). Sem indicação visual distinta (conforme decidido); ambos usam `cursor: pointer`. Se o plugin não define ação de título via `decorateCard`/novo hook `titleAction`, o título cai no mesmo handler do corpo.
- **Badge de favorito**: ícone de estrela no canto superior direito do card (espelhando o `type-indicator` que já ocupa o canto superior esquerdo), sempre renderizado pelo host, independente do plugin. Estado preenchido = favoritado. Toggle é otimista na UI e reverte em caso de erro, mostrando `showStatus`.

```
┌─────────────────────────┐
│ [tipo]            [★]   │  ← badges nos dois cantos superiores
│                          │
│        banner            │
│                          │
│ Nome do item             │  ← zona de clique "título"
└─────────────────────────┘
   ↑ resto do card = zona de clique "corpo"
```

Histórico e Cache local podem adicionar uma faixa de progresso fina (`<div>` de 3px) sob a imagem, mostrando posição/duração — só nesses dois contextos.

## 4. Modal: Ferramentas

- Overlay centralizado, largura ~560–640px, fecha com `Esc`/clique fora/botão `×`.
- Sem contexto de entidade — mesmo conteúdo independente do que está selecionado no explorador.
- Cabeçalho: `Ferramentas — {label da origem}`.
- Corpo: renderizado pelo plugin via `mount(context)`, igual ao contrato atual, mas o host agora só instancia esse conteúdo quando o modal abre (lazy) e desmonta (`cleanup`) quando fecha, não quando troca de origem.
- Para o Crunchyroll, conforme a seção 3.1 do plano funcional: resumo de armazenamento, atualização de catálogo/inventário, limpeza global de cache, preferências padrão (qualidade/áudio/legenda), fila agregada de jobs, relatório de falhas. Esses viram seções internas do modal (pode usar `<details>` ou abas simples), não um scroll único.

## 5. Modal: Inspetor

- Mesmo padrão visual do modal de Ferramentas, mas o cabeçalho mostra a entidade (imagem pequena + título + breadcrumb curto tipo "Série › Temporada 2 › Ep. 5").
- Abre ao clicar no título do card (fallback: nenhuma ação se o plugin não implementa inspetor — clique cai na ação padrão).
- Conteúdo dividido em dois blocos sempre presentes, renderizados pelo host:
  - **Favorito** (toggle, idêntico ao do card, para quem preferir usar o modal).
  - **Slot do plugin**, que varia por tipo de entidade:
    - Episódio/Filme: disponibilidade por qualidade/áudio/legenda, estados (disponível remotamente / parcial / completo / adicionado localmente), e os três botões de operação (`Baixar para cache`, `Salvar como MP4`, `Baixar e salvar como MP4`) com estado desabilitado quando a pré-condição não é satisfeita (ex. "Salvar como MP4" exige cache completo da seleção).
    - Série/Temporada: estado agregado do cache, contagem de episódios completos/parciais/vazios, espaço ocupado, jobs relacionados, seleção em lote (checkboxes por temporada/episódio) + ações de download/limpeza em lote.
- Rodapé do modal reservado para ações de lote em andamento (barra de progresso + link para o relatório), quando aplicável.

## 6. Estados vazios, de erro e de carregamento

Reaproveitar o padrão já usado em `folders.innerHTML = '<p class="text-gray-500">...</p>'`, mas padronizar por view:

- **Histórico vazio**: "Nada assistido ainda."
- **Favoritos vazio**: "Nenhum favorito nesta origem."
- **Cache local vazio**: "Nada em cache localmente."
- **Origem indisponível**: mantém o padrão atual de `showStatus` + diagnósticos (`source-diagnostics`), sem mudanças.
- **Modal com erro ao montar** (`mount` falha): mesmo tratamento que existe hoje em `loadSourceExtension` — mostra mensagem no corpo do modal, sem travar o resto da página.

## 7. Responsividade

- < 768px: sidebar de views vira uma faixa horizontal rolável (`overflow-x-auto`) acima do breadcrumb, com os mesmos itens em formato de chip.
- Modais ocupam ~92% da largura da viewport em telas pequenas, mantendo `max-height` com scroll interno no corpo.
- Grids de card já usam `auto-fill`/`minmax`, não precisam de breakpoint manual.

## 8. Mapeamento para implementação

| Mudança | Arquivo(s) |
|---|---|
| Sidebar de views + troca de contexto | `host.html`, `host.js` |
| Duas zonas de clique no card + badge de favorito | `host.js` (função `card()`), `host.css`/estilos inline |
| Modal de Ferramentas (genérico) e ciclo de vida | `host.html`, `host.js` (substitui `loadSourceExtension` atual por abertura sob demanda) |
| Modal de Inspetor (genérico) + hook `titleAction` no contrato de extensão | `host.js`, contrato em `host.mjs` |
| Conteúdo específico do Crunchyroll nos dois modais | `src/media_sources/plugins/crunchyroll/host.mjs` |
| Endpoints de favoritos/histórico | `src/socket_events.py`, `src/state.py` (conforme já listado no plano funcional) |

## 9. Fora do escopo deste documento

- Copy final de labels e mensagens de erro.
- Definição de ícones específicos (usar um set já disponível no projeto, ex. Heroicons, consistente com o SVG já usado no botão "Copiar").
- Layout interno detalhado do relatório de falhas e da fila de jobs (tratar como próxima iteração, após os modais existirem).
