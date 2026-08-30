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

O modulo JavaScript pode exportar:

- `mount(context)`: monta Ferramentas globais quando o modal abre. O contexto
  contem `source`, `root`, `request`, `refresh`, `showStatus` e `openInspector`.
- `mountInspector(context)`: monta o slot especifico da entidade. O contexto
  contem tambem `entity`, `selectMedia` e `openTools`.
- `titleAction(entity, actions)` e `bodyAction(entity, actions)`: customizam as
  duas zonas do card. Sem esses hooks o host navega em series/temporadas e
  seleciona episodios/filmes para reproducao.
- `decorateCard(entity, element)`: adiciona apresentacao ao card sem substituir
  o favorito comum do host.

`request` sempre aponta para `/host/{source_id}/...`; o plugin nao deve expor
URLs ou credenciais do provedor. Ferramentas sao desmontadas ao fechar o modal
e inspetores sao desmontados ao trocar de entidade ou origem.

O host persiste historico e favoritos no SQLite central. Cache, jobs,
exportacoes e preferencias especificos continuam pertencendo ao plugin.
