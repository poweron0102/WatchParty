# Plano funcional: interface comum de plugins e Crunchyroll

## Objetivo

Evoluir a página do host para oferecer contratos funcionais comuns de catálogo, cards, ferramentas, inspeção, histórico e favoritos, mantendo no plugin Crunchyroll as operações específicas de cache, faixas, downloads e exportações.

Este plano descreve comportamentos e responsabilidades. Ele não define um redesign visual completo.

## 1. Modelo comum de catálogo

Separar dois conceitos:

- `CatalogView`: Popular, Novidades, A-Z, Gêneros, Histórico, Favoritos e Cache local.
- `CatalogEntity`: série, temporada, episódio ou filme.

Views apenas organizam referências para entidades. Uma série mantém a mesma identidade canônica ao aparecer em diferentes views.

Regras semânticas:

- Série e temporada são navegáveis.
- Episódio e filme são reproduzíveis.
- A identidade global é `(source_id, entity_id, entity_kind)`.
- Alterar o rótulo ou a configuração da origem preserva os dados.
- Alterar `source_id` cria uma origem logicamente diferente.

## 2. Contrato comum de plugins

Cada plugin poderá declarar capacidades independentes:

- Ferramentas globais.
- Inspetor de entidade.
- Customização do clique no corpo do card.
- Customização do clique no título.
- Views adicionais.
- Operações de cache ou exportação.

A ausência de uma capacidade é normal e não deve produzir erro ou controles permanentemente desabilitados.

### Ações dos cards

Fallback comum:

| Entidade | Corpo | Título |
|---|---|---|
| Série | Navegar | Navegar |
| Temporada | Navegar | Navegar |
| Episódio | Definir mídia atual | Definir mídia atual |
| Filme | Definir mídia atual | Definir mídia atual |

O Crunchyroll substituirá o clique no título:

- Série ou temporada: abrir inspetor agregado.
- Episódio ou filme: abrir inspetor da mídia.
- O corpo mantém a ação padrão.

Todo card de entidade também terá uma ação comum e idempotente para favoritar ou desfavoritar.

## 3. Janelas de extensão

O host será responsável pelo ciclo de vida das janelas:

- Abertura e fechamento.
- Estado de carregamento.
- Tratamento de erro.
- Desmontagem ao trocar de plugin.
- Contexto da entidade selecionada.

O plugin fornece somente o conteúdo e as operações específicas.

### Ferramentas

A janela de Ferramentas não recebe uma mídia selecionada. No Crunchyroll ela conterá:

- Resumo do armazenamento.
- Atualização de catálogo e inventário.
- Limpeza global do cache.
- Preferências padrão de qualidade, áudio e legendas.
- Fila agregada de jobs.
- Acesso ao relatório de falhas.

### Inspetor

O inspetor recebe uma entidade específica. Favoritos continuam sendo responsabilidade do host; cache, faixas, downloads e exportações pertencem ao plugin.

## 4. Histórico

Criar um SQLite central do WatchParty, separado do banco do cache do Crunchyroll.

Uma linha por `(source_id, media_id)` armazenará:

- Posição.
- Duração conhecida.
- Estado de conclusão.
- Data do último play.
- Data do último checkpoint.
- Snapshot básico de título e imagem.

Política de gravação:

- A entrada nasce no primeiro `play`, não na simples seleção.
- Criar checkpoint a cada 15 segundos, somente se houver avanço mínimo de 5 segundos.
- Gravar também em pausa, seek, troca de mídia, encerramento e término.
- `last_played_at` muda no play; checkpoints não alteram a ordenação.
- Uma queda abrupta pode perder aproximadamente 15 segundos.

Retomada:

- Com menos de 95% assistido, retomar automaticamente.
- A partir de 95%, considerar concluído e começar do zero na próxima seleção.
- Uma nova reprodução limpa o estado de conclusão.
- A posição oficial vem da reprodução controlada pelo host da party.

A view Histórico será ordenada pelo último play. Permitirá remover uma entrada ou limpar tudo, sem afetar cache ou favoritos.

## 5. Favoritos

Favoritos aceitam:

- Séries.
- Temporadas.
- Episódios.
- Filmes.

Cada favorito é independente; favoritar uma série não favorita seus episódios.

Os registros sobrevivem ao reinício e preservam snapshots para funcionamento degradado. Se a origem estiver indisponível, o item permanece visível como indisponível.

A view será filtrada pela origem ativa e ordenada pela data em que o favorito foi adicionado.

## 6. Crunchyroll: Cache local

Adicionar a view `Cache local` junto de Popular, Novidades, A-Z e demais views.

Ela incluirá:

- Séries que possuam pelo menos um episódio com segmentos locais.
- Filmes com pelo menos um segmento local.
- Grupo `Sem agrupamento` para episódios cuja hierarquia ainda não foi descoberta.

A view diferencia claramente:

- Parcial.
- Offline completo.
- Exportado.

Séries serão ordenadas pelo acesso mais recente agregado. Quando o último segmento for removido, a entidade desaparecerá dessa view.

## 7. Inspetor do Crunchyroll

### Episódio ou filme

Exibir por qualidade, áudio e legenda:

- Disponível remotamente.
- Parcial.
- Completo.
- Adicionado localmente.
- Cobertura por faixa.
- Informação potencialmente desatualizada quando offline.

Operações:

1. `Baixar para cache`: completa as faixas escolhidas.
2. `Salvar como MP4`: exige que a seleção já esteja completamente no cache.
3. `Baixar e salvar como MP4`: completa ausências e depois exporta.

As três operações usam um snapshot imutável da qualidade, dos áudios e das legendas selecionados ao iniciar.

### Série ou temporada

Exibir:

- Estado agregado do cache.
- Episódios completos, parciais e vazios.
- Espaço ocupado.
- Jobs relacionados.
- Favorito.
- Operações de download e limpeza em lote.

O usuário seleciona temporadas ou episódios antes do lote. Uma exportação agregada gera um MP4 separado por episódio; nunca um único MP4 para a série inteira.

## 8. Jobs e falhas

Jobs não sobrevivem ao reinício do plugin:

- Segmentos completos permanecem.
- Temporários incompletos são descartados.
- Relatórios anteriores desaparecem.
- Reiniciar um job reutiliza o cache existente.

Prioridades:

1. Reprodução interativa.
2. `Baixar e salvar`.
3. Downloads manuais individuais.
4. Downloads em lote.

Comportamentos:

- Deduplicação de jobs idênticos.
- Materialização single-flight por segmento.
- Jobs diferentes podem reutilizar os mesmos segmentos.
- Segmentos em uso ficam protegidos contra limpeza.
- Cancelar um job não remove segmentos completos.

### Downloads em lote

As escolhas são preferências:

- Qualidade máxima.
- Idiomas de áudio.
- Idiomas de legenda.

Para cada episódio:

- Selecionar a melhor qualidade dentro do limite.
- Ausência de áudio solicitado é falha essencial.
- Ausência de legenda gera aviso, mas não interrompe.
- Falha após as tentativas normais pula o episódio.
- Os episódios seguintes continuam.
- Segmentos completos do episódio falho são preservados.

Estados finais:

- Concluído.
- Concluído com falhas.
- Falhou.
- Cancelado.

Um lote parcial oferecerá `Tentar novamente os que falharam`.

O relatório mostrará episódio, etapa, tentativa, fallback e erro sanitizado, podendo ser copiado ou baixado antes do reinício.

## 9. Exportação MP4

Regras:

- Publicação atômica no diretório de exportação.
- Nenhum arquivo parcial fica publicamente disponível.
- A mesma revisão e seleção reutilizam uma exportação válida.
- Seleções diferentes geram arquivos distintos.
- Nenhum arquivo arbitrário é sobrescrito.
- Falha no FFmpeg preserva o cache para nova tentativa.
- Legendas permanecem como faixas selecionáveis, não queimadas no vídeo.

## 10. Funcionamento offline

Preservar o comportamento atual de reprodução parcial, evitando uma refatoração ampla.

- Cache completo reproduz normalmente offline.
- Cache parcial pode iniciar se o trecho necessário estiver presente.
- Ao alcançar um buraco, informar `segmento não disponível offline`.
- Não executar retries infinitos.
- Popular e outras views remotas usam cache marcado com data da última atualização.
- Histórico, Favoritos e Cache local permanecem disponíveis pelos índices locais.

## 11. Ordenação e paginação

- Views remotas preservam a ordenação fornecida pelo plugin e usam cursor próprio.
- Histórico é ordenado por `last_played_at` decrescente.
- Favoritos são ordenados por `favorited_at` decrescente.
- Cache local é ordenado pelo último acesso agregado.
- Uma atualização pode alterar a ordem de Popular ou Novidades, mas não a identidade nem o estado das entidades.
- A paginação não deve duplicar uma entidade dentro da mesma view.

## 12. Segurança

Somente o painel administrativo do host poderá:

- Alterar favoritos.
- Limpar histórico.
- Iniciar, pausar ou cancelar jobs.
- Exportar MP4.
- Limpar cache.
- Alterar preferências do plugin.

Participantes comuns não recebem acesso aos endpoints administrativos.

## 13. Ordem recomendada de implementação

1. Introduzir o modelo `view/entity` e os quatro tipos canônicos.
2. Criar contratos de capacidades, ações de card, Ferramentas e inspetor.
3. Adicionar o SQLite central com histórico e favoritos.
4. Integrar checkpoints e retomada ao estado oficial da party.
5. Implementar as views comuns Histórico e Favoritos.
6. Migrar Ferramentas para a janela global.
7. Mover controles de mídia do Crunchyroll para seus inspetores.
8. Implementar inspetores agregados de série e temporada.
9. Criar a view Cache local e reconstrução de hierarquia.
10. Separar as três operações de download e exportação.
11. Implementar lotes resilientes, prioridades, deduplicação e relatórios.
12. Cobrir funcionamento offline, limpeza concorrente e regressões do playback parcial.
13. Documentar o contrato para novos plugins.

## 14. Fora do escopo

- Redesign visual completo.
- Contas ou perfis.
- Sincronização em nuvem.
- Quota automática, LRU ou TTL.
- Novos mecanismos de DRM.
- Reescrita substancial da reprodução parcial existente.

## Pontos principais de adaptação

- `src/media_sources/models.py`
- `files/host.js`
- `files/host.html`
- `src/socket_events.py`
- `src/state.py`
- `src/media_sources/plugins/crunchyroll/host.mjs`
- `src/media_sources/plugins/crunchyroll/source.py`
- `src/media_sources/plugins/crunchyroll/cache.py`
