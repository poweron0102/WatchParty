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
- Jobs pertencem à instância e vivem apenas durante o processo atual.
