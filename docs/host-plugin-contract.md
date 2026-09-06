# Contrato do painel do host

Plugins podem declarar no `manifest.json`:

```json
{
  "host_capabilities": ["tools", "entity-inspector", "card-body-action", "title-action", "views"],
  "views": [{"id": "cache-local", "label": "Cache local"}]
}
```

`host_capabilities` e `views` sao opcionais. A ausencia de uma capacidade e um
caso normal e nao deve desabilitar o restante do painel.

## Divisao de escopo entre os dois paineis

O host oferece dois lugares para o plugin montar UI, e a diferenca entre eles
nao e de tamanho, e de **escopo**:

| Inspetor (`mountInspector`) | Ferramentas (`mount`) |
|---|---|
| A entidade que o usuario abriu | A origem inteira |
| Estado, cobertura, baixar, exportar | Armazenamento, inventario, limpeza, preferencias, atividade |
| Uso casual, no meio da navegacao | Administracao |

Uma acao pertence a **um** dos dois. Oferecer a mesma operacao nos dois lugares
com nomes diferentes foi o defeito que este contrato existe para nao repetir.

## Exports do modulo

- `mount(context)`: monta as Ferramentas quando o modal abre.
- `mountInspector(context)`: monta o slot da entidade aberta. O contexto tem
  tambem `entity`, `selectMedia` e `openTools`.
- `titleAction(entity, actions)` e `bodyAction(entity, actions)`: customizam as
  duas zonas do card. Sem esses hooks o host navega em series/temporadas e
  seleciona episodios/filmes para reproducao.
- `decorateCard(entity, element)`: acrescenta apresentacao ao card sem
  substituir o favorito comum do host.

`mount` e `mountInspector` podem devolver um objeto (ou uma funcao, tratada
como `cleanup`). O objeto devolvido pode conter:

- `cleanup()`: chamado ao fechar o modal, trocar de entidade ou trocar de
  origem.
- `catalogRendered(state)`: ver abaixo.

## `catalogRendered({ items, parentId })`

Avisa que o Explorador terminou de renderizar uma pagina do catalogo. Serve
para o plugin acompanhar o que esta na tela -- por exemplo, a pasta atual, que
uma limpeza "da colecao aberta" precisa conhecer.

**E chamado em tres niveis**: no export do modulo, no objeto devolvido por
`mount` e no objeto devolvido por `mountInspector`. Implemente onde o estado
vive; normalmente e no retorno de `mount`.

> Este hook ja era chamado pelo host e ja era implementado pelos plugins, mas
> em niveis diferentes: o host so olhava o export do modulo, e os plugins o
> devolviam de `mount()`. Na pratica nunca disparava. O contrato passou a
> descrever os tres niveis e o host passou a entregar aos tres.

Um modal aberto **depois** de o catalogo ja estar na tela recebe o estado atual
na montagem, entao nao e preciso esperar a proxima navegacao.

## `context.request(action, options)`

Sempre aponta para `/host/{source_id}/...`. O plugin nao deve expor URLs nem
credenciais do provedor.

## `context.setHeader({ title, subtitle })`

Deixa o plugin nomear o cabecalho do modal. Passar so um dos dois preserva o
outro.

Existe porque o host so conhece o valor cru do backend: sem isto o Inspetor
mostra `series · Crunchyroll`, e o plugin -- o unico que sabe que `series`
se chama "Serie" -- nao alcanca o elemento. O host escreve um padrao razoavel
ao abrir; chamar `setHeader` durante a montagem substitui.

## `context.notifyChanged(entityIds?)`

Avisa que entidades mudaram e a tela precisa refletir isso -- tipicamente ao
fim de um job. Sem isto o download termina e os cards seguem mostrando o estado
anterior ate alguem navegar.

- Com `entityIds` (string ou array), o host so recarrega se algum deles estiver
  visivel. Um job que terminou fora da tela nao custa nada.
- Sem argumento, recarrega sempre.
- Devolve `Promise<boolean>`: se recarregou.

O host refaz a mesma consulta que produziu a tela atual -- mesma view, mesma
pasta, mesma pagina, catalogo ou busca. **Nao chame de dentro de
`catalogRendered`**: um recarregamento dispara `catalogRendered` de novo.

## `context.confirm({ title, body, confirmLabel, cancelLabel, danger })`

Confirmacao destrutiva no rodape do proprio modal. Devolve
`Promise<boolean>`, e resolve `false` se o modal fechar antes da resposta --
o plugin nunca fica esperando.

Substitui o `confirm()` nativo, que aparece no topo do navegador longe do
contexto, nao mostra o que sera perdido e nao acompanha o tema.

## Compatibilidade

As quatro entradas acima sao **aditivas**: um plugin que ignore `setHeader`,
`notifyChanged`, `confirm` e `catalogRendered` continua funcionando. O que
mudou de comportamento foi o host passar a *entregar* `catalogRendered` aos
tres niveis, e isso so faz um hook antes morto comecar a rodar.

## Fronteira de dados

O host persiste historico e favoritos no SQLite central. Cache, jobs,
exportacoes e preferencias especificos continuam pertencendo ao plugin.

Ferramentas sao desmontadas ao fechar o modal; inspetores, ao trocar de
entidade ou de origem.

## Componentes

`files/modules/ui.js` e servido em `/modules/ui.js` e traz `html` (com escape
automatico de toda interpolacao), `render`, `section`, `field`, `button`,
`badge`, `progressBar`, `withBusy` e `emptyState`. As classes que eles emitem
estao em `styles/components.css`.

O import precisa ser **absoluto**: o modulo do plugin e servido de
`/host/{source_id}/module.js`, entao `./modules/ui.js` resolveria para
`/host/{source_id}/modules/ui.js`, que nao existe.

```js
import { html, render, section, button } from '/modules/ui.js';
```
