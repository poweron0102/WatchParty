# Decisões do redesign da UI

Registro das decisões tomadas antes da implementação. Complementa
`inventario-ui-ferramentas-crunchyroll.md` (o que existe hoje) e substitui
`Redesign da UI do plugin Crunchyroll.md` nos pontos onde diverge — as
divergências estão marcadas com **[substitui plano anterior]**.

## Diagnóstico

O problema não é acabamento, é ausência de sistema:

- Três conjuntos de tokens conflitantes: `party.css`, uma cópia byte-a-byte
  inline em `host.html`, e um vocabulário completamente diferente em
  `style.css`.
- Tailwind pelo CDN em apenas uma das três páginas, com classes-ponte
  (`.bg-card{background:var(--bg-secondary)}`) traduzindo Tailwind de volta
  para os tokens do projeto.
- A UI dos plugins é um único `replaceChildren` com 26 elementos em sequência
  linear, sem um elemento de agrupamento sequer.
- Os dois painéis (Ferramentas e Inspetor) operam sobre a mesma coisa, com
  rótulos diferentes para as mesmas chamadas de backend.

## Decisões

### Arquitetura de informação **[substitui plano anterior]**

O plano anterior propunha 4 abas (`Visão geral / Mídia / Manutenção /
Atividade`) e mantinha as ações de mídia nos dois painéis. Ambos foram
rejeitados: abas escondem estado num painel de operação assíncrona, e manter
ação de mídia nos dois lugares harmoniza a redundância em vez de eliminá-la.

Separação por escopo:

| Inspetor (contextual, uso casual) | Ferramentas (global, administração) |
|---|---|
| Favorito | Armazenamento |
| Estado e cobertura da mídia | Atualizar inventário / catálogo |
| Baixar / Exportar | Limpeza do cache |
| Faixas e legenda (recolhido em "Avançado") | Preferências padrão |
| Progresso do job iniciado ali | Atividade: jobs e falhas |

Contêiner: modal centralizado para os dois, até ~880px. Drawer foi considerado
e descartado — só se justificaria se fosse requisito acompanhar jobs enquanto
navega, e não é.

### Semântica das ações **[substitui plano anterior]**

As três ações concorrentes (`download`, `export-mp4`, `download-export`)
colapsam em **um botão "Baixar" + checkbox "Exportar MP4 ao terminar"**.

O plano anterior propunha três radio buttons de intenção. Rejeitado: mantém
três conceitos e custa dois cliques. Exportar não é uma terceira operação, é um
sufixo de download — o backend já trata assim, já que `export-mp4` completa
segmentos ausentes. A UI passa a dizer isso em vez de escondê-lo.

O comportamento do backend **não** muda; muda o nome que a UI dá a ele.

### Feedback **[substitui plano anterior]**

Feedback inline, no controle que disparou a ação: o botão vira estado de
carregamento e o resultado aparece na própria seção. O aviso global fica
reservado ao que acontece fora da tela visível.

O plano anterior queria toast ancorado ao botão *mais* aviso global. Rejeitado:
duplicar toda mensagem é ruído, e posicionar um flutuante à mão em CSS puro é
custo sem retorno.

### Fundação técnica

- Tailwind CDN removido. `files/styles/tokens.css`, `base.css` e
  `components.css` carregados pelas três páginas.
- Paleta base: a de `style.css` (neutro frio, `#0f1115`/`#171a21`/`#202530`,
  acento `#2f8cff`), estendida com tokens semânticos de estado.
- Cor com significado: verde = baixado, âmbar = parcial, azul-acento =
  exportado, cinza-mudo = sem cache. **Vermelho fica reservado para erro e ação
  destrutiva** — hoje não tem cor própria em lugar nenhum.
- `files/modules/ui.js` compartilhado: tag `html``` com escape automático de
  toda interpolação, mais primitivos (badge, barra de progresso, seção,
  confirmação inline). Importado pelo host e pelos dois plugins, matando a
  fábrica `button()` copiada byte-a-byte entre eles.
- Sem dependência nova: o projeto não tem `package.json` e continua assim.

### Como o Tailwind sai (Q32)

Três caminhos foram considerados para substituir as utilitárias do CDN:

| | Caminho | Consequência |
|---|---|---|
| (a) | Classes semânticas (`.host-card`, `.host-modal`) | Markup fica legível e o CSS vira vocabulário do produto; diff grande de uma vez |
| (b) | Mini-conjunto de utilitárias próprias | Markup quase intacto; recria o mesmo problema com outro nome |
| (c) | Híbrido: componentes semânticos + punhado de utilitárias | Diff menor; convive com dois vocabulários |

A recomendação do assistente foi (c), pelo argumento de que `host.js` gera
markup com strings de classe embutidas e a tradução total seria um diff grande
antes de qualquer melhoria visível. **O usuário escolheu (a), ciente desse
argumento.** Vale a decisão dele.

Consequência assumida: as classes nascem nomeadas pela estrutura *final*
descrita acima (Inspetor contextual / Ferramentas global), não pela estrutura
atual, para que as etapas 8 e 9 reescrevam markup sem reescrever o CSS.

Duas classes de layout com nome genérico sobrevivem — `.plugin-row` e
`.plugin-stack` — usadas só pelo markup que os plugins geram. Não são o começo
de um sistema de utilitárias: são o mínimo para que um plugin agrupe controles
sem inventar nome semântico para cada fila de botões.

### Contrato de plugin

Quatro adições retrocompatíveis (o plugin `directory` continua funcionando sem
alteração):

1. `catalogRendered` documentado — o host já o chama em `host.js`, o
   Crunchyroll já o implementa, e o contrato nunca o mencionou.
2. `context.setHeader({title, subtitle})` — hoje o host escreve `entityKind`
   cru no cabeçalho (`series · Crunchyroll`) e o plugin não tem como traduzir.
3. `context.notifyChanged(entityIds)` — sem isso, um job termina e os cards
   continuam mostrando o estado anterior.
4. `context.confirm({title, body, danger})` → `Promise<boolean>` — substitui o
   `confirm()` nativo, e nasce consistente para todos os plugins.

### Correções de backend

- **Bug:** o agregado de série/temporada filtra `media_id.startsWith('episode:')`
  sobre o inventário inteiro, então os números exibidos são globais e não da
  entidade aberta.
- Expor `skipped` no resultado da limpeza.
- Parar de descartar as falhas detalhadas por job, que hoje viram só uma
  contagem.

### Escopo contido

Regra: só entra dado novo que responda a uma pergunta que a tela já provoca, e
só dentro de conteúdo recolhido.

| Capacidade | Entra? | Motivo |
|---|---|---|
| Falhas detalhadas por job | Sim | É conserto, não adição |
| `skipped` na limpeza | Sim | Um número num resultado já exibido |
| `audio_quality` nas preferências | Sim | Campo ao lado de um que já existe |
| Detalhes de exportação | Sim, recolhido | "0 exportação(ões)" já provoca a pergunta |
| Cache por faixa/representação | Não | Ninguém abre painel para isso |
| Download em lote | Não agora | Maior superfície nova; depois da estrutura |
| `decorateCard` nos cards | Sim | Hook pronto e ocioso; hoje descobrir se um episódio está em cache exige abrir o Inspetor um por um |

### Tradução

Nenhum valor técnico cru como texto principal; ele sobrevive no `title` do
badge quando útil.

| Técnico | Rótulo |
|---|---|
| `empty` | Sem cache |
| `partial` | Parcial |
| `offline` | Baixado |
| `exported` | Exportado |
| `queued` / `running` / `paused` | Na fila / Baixando / Pausado |
| `completed` / `completed_with_failures` | Concluído / Concluído com falhas |
| `failed` / `cancelled` | Falhou / Cancelado |
| `download` | Download |
| `export-mp4` | Exportação MP4 |
| `download-export` | Download e exportação |
| `series` / `season` / `episode` / `movie` | Série / Temporada / Episódio / Filme |

Duas escolhas deliberadas contra o glossário do inventário: **"Baixado"** em vez
de "Disponível offline" (mais curto, e "offline" sugere erro de conexão), e
**"Baixando"** em vez de "Em execução" para `running` (mais concreto).

### Alcance nas outras páginas

`/` e `/party` recebem tokens e componentes normalizados, mas não redesenho de
layout. O Painel do Host recebe redesenho de layout, porque é onde os painéis
vivem.

## Risco assumido

Com a separação de escopo, operar uma mídia passa a exigir clicar no card dela.
Hoje o `<select>` de Ferramentas permite agir sobre qualquer mídia da página
atual sem navegar. Se a falta desse atalho se mostrar real, o conserto é busca
no Explorador — não reverter a separação.

## Ordem de implementação

1. Limpeza de morto
2. Testes reescritos para âncoras estáveis (`data-testid`), antes de quebrar markup
3. `tokens.css` + `base.css` + `components.css`; `/` e `/party` migram
4. `modules/ui.js`
5. Tailwind CDN removido; `host.html`, `host.js` e plugin `directory` migrados
6. Contrato de plugin
7. Correções de backend
8. Ferramentas redesenhado
9. Inspetor redesenhado + `decorateCard`

Revisão do usuário após as etapas 3, 5 e 8.

## Etapa 1 — o que foi removido

- `files/host.css` (93 linhas): não era referenciado por nenhum HTML, JS ou
  Python. Estilizava seletores que não existem mais no markup atual
  (`#access-link`, `#update-banners-btn`, `.explorer`, `.file-item`).
- Tema do Plyr em `files/party.css`: quatro custom properties `--plyr-*` e duas
  regras. A aplicação migrou para o Shaka Player, e
  `crunchyroll-source-implementation-plan.md` já determinava a remoção sem
  fallback.

Não removido, apesar de levantado como suspeita: `.submit-button` em
`style.css` aparece duas vezes, mas a primeira é um grupo de regras
compartilhado com `.file-button` e `.ghost-button` e a segunda adiciona o que é
específico do submit. É CSS intencional, não duplicação.

Adiado para a etapa 2: `<span id="source-extension-root">` em `host.html` é
markup vestigial (destruído no primeiro `replaceChildren`), mas
`tests/test_host_layout.py` afirma sua presença. Sai junto com a reescrita dos
testes.

## Etapa 5 — o Tailwind saiu

O CDN entrava por três portas, e as três foram fechadas:

1. `<script src="https://cdn.tailwindcss.com">` em `host.html`.
2. As classes-ponte no `<style>` embutido (`.bg-card`, `.bg-brand`,
   `.bg-input`, `.border-input`), que traduziam nomes do framework de volta
   para os tokens do projeto.
3. As strings de classe utilitária no markup — em `host.html`, embutidas na
   geração de cards e views em `host.js`, e nos dois plugins.

O `<style>` embutido virou `files/styles/host.css`, nomeado pela estrutura
final: `.host-card`, `.host-modal`, `.catalog-view`, `.media-item`. Campos e
botões passaram a usar `.ui-input` e `.ui-btn` de `components.css`, em vez de
uma segunda definição só do host.

Três consequências que valem registro:

- **`.hidden` morreu junto.** Era uma classe do Tailwind usada em 14 lugares.
  No lugar dela entrou o atributo `hidden` (`elemento.hidden = true`), com
  `[hidden]{display:none!important}` em `base.css` — necessário porque um modal
  `display:flex` ignoraria `hidden` sem isso. Some com o par
  `add('hidden')`/`add('flex')` que os modais faziam.
- **O modal foi de 640px para 880px**, cumprindo a decisão de arquitetura de
  informação acima. O Inspetor e as Ferramentas usam a mesma largura para que
  alternar entre eles não mova a página.
- **O plugin `directory` foi reescrito sobre `modules/ui.js`.** O import é
  absoluto (`/modules/ui.js`) porque o módulo é servido de
  `/host/{source_id}/module.js` — um caminho relativo resolveria para
  `/host/{source_id}/modules/ui.js`. Ganhou seções com título, feedback no
  próprio botão (`withBusy`) e `inlineConfirm` no lugar do `confirm()` nativo.

O plugin `crunchyroll` recebeu apenas troca mecânica de classe (nenhuma mudança
de comportamento) e correção da acentuação dos textos de interface. A
reestruturação dele é o assunto das etapas 8 e 9.

Quatro testes novos guardam o resultado, em `test_design_system.py`: nenhuma
página carrega framework de CSS por CDN, nenhuma classe-ponte sobrevive, toda
classe do markup do host pertence ao vocabulário do projeto (`host-`,
`catalog-`, `media-`, `ui-`, `plugin-`), e toda classe usada tem regra de
verdade em `styles/` — sem o Tailwind, uma classe sem regra falha em silêncio.
