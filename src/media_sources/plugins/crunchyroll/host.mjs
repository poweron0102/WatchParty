/* Painel do plugin Crunchyroll.
 *
 * Divisao de escopo (docs/decisoes-redesign-ui.md):
 *
 *   Ferramentas (mount)        -> a origem inteira: armazenamento, catalogo,
 *                                 limpeza, preferencias, atividade.
 *   Inspetor (mountInspector)  -> a entidade aberta: estado, baixar/exportar,
 *                                 faixas, legenda.
 *
 * Uma acao pertence a UM dos dois.  Antes as duas telas ofereciam download,
 * exportacao e faixas com nomes diferentes para as mesmas chamadas -- era a
 * queixa que originou o redesign, e o `<select>` de midia nas Ferramentas era
 * o que a sustentava.  Ele saiu: quem opera uma midia abre a midia.
 */
import {
  html, render, section, field, button, badge, progressBar, emptyState,
  resultLine, withBusy, formatBytes,
} from '/modules/ui.js';

/* --- Traducao ---------------------------------------------------------
 * Nenhum valor tecnico cru como texto principal.  Ele sobrevive no `title`
 * do badge, onde continua acessivel sem virar a informacao que se le. */

const KIND = { series: 'Série', season: 'Temporada', episode: 'Episódio', movie: 'Filme' };

const STATE = {
  empty: ['Sem cache', 'empty'],
  partial: ['Parcial', 'partial'],
  offline: ['Baixado', 'cached'],
  exported: ['Exportado', 'exported'],
};

const JOB_KIND = {
  'download': 'Download',
  'export-mp4': 'Exportação MP4',
  'download-export': 'Download e exportação',
  'batch-download': 'Download em lote',
  'batch-download-export': 'Download e exportação em lote',
};

const JOB_STATE = {
  queued: ['Na fila', 'neutral'],
  running: ['Baixando', 'accent'],
  paused: ['Pausado', 'warning'],
  completed: ['Concluído', 'success'],
  completed_with_failures: ['Concluído com falhas', 'warning'],
  failed: ['Falhou', 'danger'],
  cancelled: ['Cancelado', 'neutral'],
};

const ACTIVE_STATES = ['queued', 'running', 'paused'];

function stateBadge(value) {
  const [label, tone] = STATE[value] || ['Desconhecido', 'neutral'];
  return badge({ label, tone, technical: value });
}

/* --- Limpeza ----------------------------------------------------------
 * O modo "Mídia selecionada" saiu: limpar o cache de UMA midia e acao da
 * entidade, e mora no Inspetor.  O que fica aqui e o que age sobre o
 * conjunto. */

const CLEANUP_MODES = [
  ['exported', 'Mídias já exportadas em MP4', null],
  ['quality', 'Uma qualidade de vídeo', 'Altura em pixels, ex.: 480'],
  ['partial', 'Downloads parciais antigos', 'Dias sem acesso, ex.: 30'],
  ['collection', 'A coleção aberta no Explorador', null],
  ['orphans', 'Arquivos órfãos', null],
  ['all', 'Todo o cache de segmentos', null],
];

export async function mount(context) {
  let currentParent = null;
  let timer = null;

  const view = render(context.root, html`
    ${section({
      title: 'Armazenamento',
      description: 'O que este plugin ocupa em disco.',
      actions: button({ label: 'Atualizar', ref: 'refreshInventory' }),
      body: html`<p class="ui-result" data-ref="storage">Carregando…</p>`,
    })}

    ${section({
      title: 'Catálogo',
      description: 'Descarta os metadados salvos e busca de novo no provedor.',
      actions: button({ label: 'Atualizar catálogo', ref: 'refreshCatalog' }),
      body: resultLine({ message: 'Use quando títulos ou capas estiverem desatualizados.', ref: 'catalogResult' }),
    })}

    ${section({
      title: 'Limpeza do cache',
      description: 'Simule primeiro: a execução só libera depois de ver o que sai.',
      body: html`
        ${field({
          label: 'O que remover',
          control: html`<select data-ref="mode">
            ${CLEANUP_MODES.map(([value, label]) => html`<option value="${value}">${label}</option>`)}
          </select>`,
        })}
        <div data-ref="valueWrap" hidden>
          ${field({ label: 'Limite', control: html`<input data-ref="value" type="number" min="0">` })}
        </div>
        <div class="plugin-row">
          ${button({ label: 'Simular limpeza', ref: 'preview' })}
          ${button({ label: 'Executar limpeza', ref: 'run', variant: 'danger', disabled: true,
                     reason: 'Simule antes para ver o que será removido.' })}
        </div>
        ${resultLine({ message: 'Nada simulado ainda.', ref: 'cleanupResult' })}
      `,
    })}

    ${section({
      title: 'Preferências padrão',
      description: 'Valem para os próximos downloads. Não alteram o que já está em cache.',
      actions: button({ label: 'Salvar', ref: 'savePreferences', variant: 'primary' }),
      body: html`
        ${field({ label: 'Qualidade de vídeo', hint: 'Ex.: 1080p. Vazio usa a melhor disponível.',
                  control: html`<input data-ref="videoQuality" placeholder="1080p">` })}
        ${field({ label: 'Qualidade de áudio', hint: 'Ex.: 192k.',
                  control: html`<input data-ref="audioQuality" placeholder="192k">` })}
        ${field({ label: 'Idiomas de áudio', hint: 'Separados por vírgula, na ordem de preferência.',
                  control: html`<input data-ref="audioLanguages" placeholder="pt-BR, ja-JP">` })}
        ${field({ label: 'Idiomas de legenda', hint: 'Separados por vírgula. Use * para todos.',
                  control: html`<input data-ref="subtitleLanguages" placeholder="pt-BR, en-US">` })}
        ${resultLine({ message: '', ref: 'preferencesResult' })}
      `,
    })}

    ${section({
      title: 'Atividade',
      description: 'Downloads e exportações desta execução do servidor.',
      body: html`<div class="plugin-stack" data-ref="jobs"></div>`,
    })}
  `);

  /* --- Armazenamento e preferencias ---------------------------------- */

  async function loadInventory() {
    const data = await context.request('cache');
    const storage = data.storage || {};
    view.storage.textContent =
      `${formatBytes(storage.cached_bytes || 0)} em cache · ${storage.media_count || 0} mídia(s) · `
      + `${storage.export_count || 0} exportação(ões)`;
    const defaults = data.defaults || {};
    view.videoQuality.value = defaults.video_quality || '';
    view.audioQuality.value = defaults.audio_quality || '';
    view.audioLanguages.value = (defaults.audio_languages || []).join(', ');
    view.subtitleLanguages.value = (defaults.subtitle_languages || []).join(', ');
    renderJobs(data.jobs || []);
  }

  function languageList(value) {
    return value.split(',').map(item => item.trim()).filter(Boolean);
  }

  view.refreshInventory.onclick = () => withBusy(view.refreshInventory, 'Atualizando', async () => {
    try { await loadInventory(); } catch (error) { context.showStatus(error.message, 'error'); }
  });

  view.refreshCatalog.onclick = () => withBusy(view.refreshCatalog, 'Atualizando', async () => {
    try {
      await context.request('catalog/refresh', { method: 'POST' });
      view.catalogResult.textContent = 'Metadados descartados; o catálogo será buscado de novo.';
      view.catalogResult.className = 'ui-result ui-result--success';
      await context.refresh();
    } catch (error) { context.showStatus(error.message, 'error'); }
  });

  view.savePreferences.onclick = () => withBusy(view.savePreferences, 'Salvando', async () => {
    try {
      await context.request('preferences', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_quality: view.videoQuality.value.trim(),
          audio_quality: view.audioQuality.value.trim(),
          audio_languages: languageList(view.audioLanguages.value),
          subtitle_languages: languageList(view.subtitleLanguages.value),
        }),
      });
      view.preferencesResult.textContent = 'Preferências salvas.';
      view.preferencesResult.className = 'ui-result ui-result--success';
    } catch (error) {
      view.preferencesResult.textContent = error.message;
      view.preferencesResult.className = 'ui-result ui-result--danger';
    }
  });

  /* --- Limpeza -------------------------------------------------------- */

  function cleanupPayload() {
    const mode = view.mode.value;
    const payload = { mode };
    if (mode === 'quality') payload.height = Number(view.value.value);
    if (mode === 'partial') payload.older_than_days = Number(view.value.value || 30);
    if (mode === 'collection') payload.parent_id = currentParent || '';
    return payload;
  }

  // O motivo de um botao desabilitado e texto visivel, nao so `title`.
  // Trocar um sem o outro deixa a explicacao mentindo.
  function lockRun(reason) {
    view.run.disabled = true;
    view.run.title = reason;
    const explanation = view.run.parentElement.querySelector('.ui-btn-reason');
    if (explanation) explanation.textContent = reason;
  }

  function unlockRun() {
    view.run.disabled = false;
    view.run.removeAttribute('title');
    const explanation = view.run.parentElement.querySelector('.ui-btn-reason');
    if (explanation) explanation.textContent = '';
  }

  function syncMode() {
    const [, , hint] = CLEANUP_MODES.find(([value]) => value === view.mode.value) || [];
    view.valueWrap.hidden = !hint;
    if (hint) {
      view.valueWrap.querySelector('.ui-field-label').textContent =
        view.mode.value === 'quality' ? 'Altura do vídeo' : 'Idade mínima';
      view.value.placeholder = hint;
    }
    // Trocar de modo invalida a simulacao anterior: o que ela mostrou nao e
    // mais o que este modo removeria.
    lockRun('Simule este modo antes de executar.');
    view.cleanupResult.textContent = 'Nada simulado ainda.';
    view.cleanupResult.className = 'ui-result';
  }

  view.mode.onchange = syncMode;

  view.preview.onclick = () => withBusy(view.preview, 'Simulando', async () => {
    try {
      const result = await context.request('cache/cleanup-preview', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(cleanupPayload()),
      });
      const media = result.media?.length ? ` · ${result.media.length} mídia(s)` : '';
      view.cleanupResult.textContent = result.count
        ? `${result.count} arquivo(s) · ${formatBytes(result.bytes)}${media}`
        : 'Nada a remover neste modo.';
      view.cleanupResult.className = `ui-result${result.count ? ' ui-result--warning' : ''}`;
      if (result.count) unlockRun();
      else lockRun('A simulação não encontrou nada para remover.');
    } catch (error) {
      view.cleanupResult.textContent = error.message;
      view.cleanupResult.className = 'ui-result ui-result--danger';
    }
  });

  view.run.onclick = async () => {
    const confirmed = await context.confirm({
      title: 'Executar a limpeza simulada?',
      body: `${view.cleanupResult.textContent} Os segmentos removidos terão de ser baixados novamente.`,
      confirmLabel: 'Remover', danger: true,
    });
    if (!confirmed) return;
    await withBusy(view.run, 'Removendo', async () => {
      try {
        const result = await context.request('cache/cleanup', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(cleanupPayload()),
        });
        // `skipped` ja vinha do backend e era descartado aqui: um arquivo
        // travado sumia da conta e o total nao fechava.
        const skipped = result.skipped ? ` · ${result.skipped} não puderam ser removidos` : '';
        view.cleanupResult.textContent =
          `${result.removed} arquivo(s) removido(s) · ${formatBytes(result.bytes)} liberados${skipped}`;
        view.cleanupResult.className = `ui-result ui-result--${result.skipped ? 'warning' : 'success'}`;
        lockRun('Simule de novo para executar outra limpeza.');
        await loadInventory();
        await context.notifyChanged();
      } catch (error) {
        view.cleanupResult.textContent = error.message;
        view.cleanupResult.className = 'ui-result ui-result--danger';
      }
    });
  };

  /* --- Atividade ------------------------------------------------------ */

  function jobRow(job) {
    const [stateLabel, stateTone] = JOB_STATE[job.state] || [job.state, 'neutral'];
    const active = ACTIVE_STATES.includes(job.state);
    // As falhas detalhadas sempre vieram do backend e a UI as reduzia a uma
    // contagem, que nao diz o que fazer.  Agora ficam legiveis, recolhidas
    // para nao competir com o progresso.
    const failures = job.failures?.length ? html`
      <details>
        <summary>${job.failures.length} falha(s)</summary>
        <div class="plugin-stack">
          ${job.failures.map(failure => html`
            <p class="ui-result ui-result--danger">${failure.media_id} · ${failure.stage}: ${failure.error}</p>
          `)}
        </div>
      </details>` : '';
    return html`
      <div class="plugin-stack" data-job="${job.id}">
        <div class="plugin-row">
          ${badge({ label: JOB_KIND[job.kind] || job.kind, tone: 'neutral', technical: job.kind })}
          ${badge({ label: stateLabel, tone: stateTone, technical: job.state })}
          <span class="ui-result">${job.completed}/${job.total || '?'}</span>
          ${active ? button({ label: job.state === 'paused' ? 'Retomar' : 'Pausar', ref: `toggle-${job.id}` }) : ''}
          ${active ? button({ label: 'Cancelar', ref: `cancel-${job.id}`, variant: 'ghost' }) : ''}
        </div>
        ${job.total ? progressBar({ value: job.completed, max: job.total, tone: 'accent',
                                    label: `${JOB_KIND[job.kind] || job.kind}: ${stateLabel}` }) : ''}
        ${job.message ? resultLine({ message: job.message }) : ''}
        ${job.error ? resultLine({ message: job.error, tone: 'danger' }) : ''}
        ${failures}
      </div>`;
  }

  function renderJobs(jobs) {
    // `loadInventory` tambem chega aqui: sem cancelar o anterior, atualizar o
    // inventario durante um job deixa duas cadeias de polling correndo, cada
    // uma reagendando a outra.
    if (timer) { clearTimeout(timer); timer = null; }
    if (!jobs.length) {
      render(view.jobs, emptyState('Nenhum download ou exportação nesta execução.'));
      return;
    }
    const rows = render(view.jobs, html`${jobs.map(jobRow)}`);
    for (const job of jobs.filter(value => ACTIVE_STATES.includes(value.state))) {
      const operation = job.state === 'paused' ? 'resume' : 'pause';
      const toggle = rows[`toggle-${job.id}`];
      const cancel = rows[`cancel-${job.id}`];
      if (toggle) toggle.onclick = () => withBusy(toggle, null, () => jobAction(job.id, operation));
      if (cancel) cancel.onclick = () => withBusy(cancel, null, () => jobAction(job.id, 'cancel'));
    }
    if (jobs.some(job => ACTIVE_STATES.includes(job.state))) {
      timer = setTimeout(() => pollJobs().catch(() => {}), 1000);
    }
  }

  async function jobAction(jobId, operation) {
    try {
      await context.request(`jobs/${jobId}/${operation}`, { method: 'POST' });
      await pollJobs();
    } catch (error) { context.showStatus(error.message, 'error'); }
  }

  async function pollJobs() {
    const data = await context.request('jobs');
    renderJobs(data.jobs);
    if (data.jobs.some(job => ACTIVE_STATES.includes(job.state))) return;
    await loadInventory();
    await context.notifyChanged();
  }

  syncMode();
  await loadInventory();

  return {
    catalogRendered(state) { currentParent = state.parentId; },
    cleanup() { if (timer) clearTimeout(timer); context.root.replaceChildren(); },
  };
}

// O host e dono do modal e do controle de favorito.  Este hook cuida so da
// disponibilidade e das operacoes especificas do Crunchyroll.
export function titleAction(entity, actions) { return actions.openInspector(entity); }

/* --- Estado no card --------------------------------------------------
 * Descobrir se um episodio esta baixado exigia abrir o Inspetor um por um.
 * O hook `decorateCard` estava pronto e ocioso no host desde sempre.
 *
 * Sao duas fases porque o host chama `decorateCard` durante a renderizacao,
 * antes de o plugin saber qual pagina e: aqui so nasce o slot vazio, e
 * `catalogRendered` -- que roda depois, com a pagina inteira -- faz UMA
 * consulta e preenche todos.  Uma requisicao por pagina, nao por card.
 *
 * O slot guarda o id no proprio DOM em vez de num Map do modulo: card que
 * saiu da tela leva o slot embora, sem deixar entrada velha para limpar. */

export function decorateCard(entity, element) {
    if (entity.entry_type !== 'playable') return;
    const slot = document.createElement('div');
    slot.className = 'media-card-badges';
    slot.dataset.mediaId = entity.id;
    element.appendChild(slot);
}

export async function catalogRendered(state, context) {
    const slots = [...document.querySelectorAll('.media-card-badges[data-media-id]')];
    if (!slots.length || !context?.request) return;
    const ids = slots.map(slot => slot.dataset.mediaId);
    let states = {};
    try {
        const data = await context.request(`cache/states?${new URLSearchParams({ media_ids: ids.join(',') })}`);
        states = data.states || {};
    } catch (error) {
        return; // Card sem selo e melhor que card com selo errado.
    }
    for (const slot of slots) {
        const cached = states[slot.dataset.mediaId];
        // Ausente ou vazio nao ganha selo: um "Sem cache" em cada card de uma
        // pagina inteira seria ruido, nao informacao.
        if (!cached || cached.state === 'empty') {
            slot.replaceChildren();
            continue;
        }
        const [label, tone] = STATE[cached.state] || ['Desconhecido', 'neutral'];
        const text = cached.state === 'partial'
            ? `${label} · ${Math.round((cached.coverage || 0) * 100)}%`
            : label;
        render(slot, badge({ label: text, tone, technical: cached.state }));
    }
}

export async function mountInspector(context) {
  const item = context.entity;
  const kind = item.entity_kind || item.media_kind || item.id?.split(':', 1)[0];
  const playable = item.entry_type === 'playable';
  context.setHeader({
    title: item.title,
    subtitle: `${KIND[kind] || 'Mídia'} · ${context.source?.label || 'Crunchyroll'}`,
  });

  let presentation = null;
  let timer = null;
  let downloaded = false;

  /** Motivo visivel de um botao desabilitado, em par com o `title`. */
  function setReason(element, reason) {
    element.title = reason || '';
    if (!reason) element.removeAttribute('title');
    const explanation = element.parentElement?.querySelector('.ui-btn-reason');
    if (explanation) explanation.textContent = reason;
  }

  const view = render(context.root, html`
    ${section({
      title: 'Disponibilidade',
      body: html`<div class="plugin-row" data-ref="status">Carregando…</div>`,
    })}
    ${playable ? html`
      ${section({
        title: 'Baixar',
        body: html`
          <label class="plugin-row">
            <input type="checkbox" data-ref="exportToo">
            <span>Exportar MP4 ao terminar</span>
          </label>
          <div class="plugin-row">
            ${button({ label: 'Baixar', ref: 'download', variant: 'primary' })}
          </div>
          ${resultLine({ message: '', ref: 'intent' })}
          ${resultLine({ message: '', ref: 'jobResult' })}
        `,
      })}
      ${section({
        title: 'Cache desta mídia',
        description: 'Remove os segmentos baixados. Os arquivos MP4 já exportados não são tocados.',
        actions: button({ label: 'Limpar cache', ref: 'clearCache', variant: 'danger', disabled: true,
                          reason: 'Nada em cache para remover.' }),
        body: html`
          ${resultLine({ message: '', ref: 'clearResult' })}
          <details data-ref="exportDetails" hidden>
            <summary>Detalhes da exportação</summary>
            <div class="plugin-stack" data-ref="exports"></div>
          </details>
        `,
      })}
      ${section({
        title: 'Avançado',
        description: 'Faixas e legendas desta mídia.',
        body: html`
          <details>
            <summary>Escolher faixas de vídeo, áudio e legenda</summary>
            <div class="plugin-stack" data-ref="tracks">Carregando faixas…</div>
          </details>
          <details>
            <summary>Adicionar uma legenda própria</summary>
            <div class="plugin-stack">
              ${field({ label: 'Arquivo', hint: 'Formatos .ass, .srt ou .vtt.',
                        control: html`<input data-ref="subtitleFile" type="file" accept=".ass,.srt,.vtt">` })}
              ${field({ label: 'Idioma', control: html`<input data-ref="subtitleLanguage" placeholder="pt-BR">` })}
              ${field({ label: 'Rótulo', hint: 'Opcional.',
                        control: html`<input data-ref="subtitleLabel" placeholder="Português (forçada)">` })}
              ${button({ label: 'Enviar legenda', ref: 'subtitleUpload' })}
              ${resultLine({ message: '', ref: 'subtitleResult' })}
            </div>
          </details>
        `,
      })}
    ` : ''}
  `);

  /* --- Disponibilidade ------------------------------------------------ */

  function renderTracks() {
    if (!presentation) return;
    render(view.tracks, html`${presentation.tracks.map(track => html`
      <fieldset class="plugin-group">
        <legend>${track.kind === 'video' ? 'Vídeo' : track.kind === 'audio' ? 'Áudio' : 'Legenda'}
          · ${track.label || track.language || track.id}</legend>
        ${track.representations.map(rep => html`
          <label class="plugin-row">
            <input type="${track.kind === 'video' ? 'radio' : 'checkbox'}"
                   name="${track.kind === 'video' ? 'cr-video' : `cr-${track.kind}`}"
                   data-track="${track.id}" data-rep="${rep.id}" data-kind="${track.kind}"
                   ${trackChecked(track, rep) ? 'checked' : ''}>
            <span>${rep.height ? `${rep.height}p` : `${Math.round((rep.bandwidth || 0) / 1000)} kbps`}</span>
          </label>
        `)}
      </fieldset>
    `)}`);
  }

  function trackChecked(track, rep) {
    if (track.kind === 'video') return rep.id === presentation.canonical_video_representation;
    return !!track.default;
  }

  function selection() {
    const checked = [...view.tracks?.querySelectorAll('input:checked') || []];
    const chosenVideo = checked.find(value => value.dataset.kind === 'video')?.dataset.rep;
    return {
      media_id: item.id,
      video_representation: chosenVideo || presentation?.canonical_video_representation,
      audio_tracks: checked.filter(value => value.dataset.kind === 'audio').map(value => value.dataset.track),
      subtitle_tracks: checked.filter(value => value.dataset.kind === 'text').map(value => value.dataset.track),
    };
  }

  async function loadAvailability() {
    if (!playable) {
      // Escopado por parent_id no backend.  Antes era `startsWith('episode:')`
      // sobre o inventario inteiro, ou seja, os episodios de todas as series.
      const summary = await context.request(`cache/summary?${new URLSearchParams({ parent_id: item.id })}`);
      render(view.status, summary.total ? html`
        ${badge({ label: `${summary.offline + summary.exported} baixado(s)`, tone: 'cached' })}
        ${badge({ label: `${summary.partial} parcial(is)`, tone: 'partial' })}
        ${badge({ label: `${summary.empty} sem cache`, tone: 'empty' })}
        <span class="ui-result">de ${summary.total} episódio(s) · ${formatBytes(summary.cached_bytes)}</span>
      ` : emptyState('Nenhum episódio catalogado nesta coleção.'));
      return;
    }
    presentation = await context.request(`presentation?${new URLSearchParams({ media_id: item.id })}`);
    // Uma consulta escopada nesta midia.  Antes pedia o inventario inteiro --
    // com faixas e representacoes de TODAS as midias -- para achar uma linha.
    const data = await context.request(`cache/states?${new URLSearchParams({ media_ids: item.id })}`);
    const cached = data.states?.[item.id];
    downloaded = cached?.state === 'offline' || cached?.state === 'exported';
    render(view.status, html`
      ${stateBadge(cached?.state || 'empty')}
      <span class="ui-result">${Math.round((cached?.coverage || 0) * 100)}% dos segmentos
        · ${formatBytes(cached?.cached_bytes || 0)}</span>
    `);

    if (cached?.cached_count) {
      view.clearCache.disabled = false;
      view.clearCache.removeAttribute('title');
      setReason(view.clearCache, '');
    } else {
      view.clearCache.disabled = true;
      setReason(view.clearCache, 'Nada em cache para remover.');
    }

    renderExports(cached?.exports || []);
    syncIntent();
    renderTracks();
  }

  /* --- Exportacoes ---------------------------------------------------- */

  function renderExports(exports) {
    view.exportDetails.hidden = !exports.length;
    if (!exports.length) return;
    render(view.exports, html`${exports.map(row => html`
      <div class="plugin-stack">
        <p class="ui-result">${new Date((row.created_at || 0) * 1000).toLocaleString('pt-BR')}
          · ${formatBytes(row.size)}</p>
        <p class="ui-result"><code>${row.path}</code></p>
        <p class="ui-result">SHA-256 registrado: <code>${row.sha256}</code></p>
      </div>
    `)}`);
  }

  /* --- Acoes ----------------------------------------------------------
   * Havia tres botoes concorrentes -- "Baixar para cache", "Salvar como MP4"
   * e "Baixar e salvar como MP4" -- para duas decisoes.  Exportar nao e uma
   * terceira operacao, e um sufixo do download: o backend ja trata assim,
   * porque `export-mp4` completa os segmentos que faltam apesar do nome.
   *
   * Sobra um botao e uma caixa.  A linha de intencao diz o que o clique vai
   * fazer, para o rotulo curto nunca mentir sobre o estado atual. */

  function syncIntent() {
    const exportToo = view.exportToo.checked;
    if (downloaded && !exportToo) {
      view.download.disabled = true;
      setReason(view.download, 'Já está baixado. Marque a exportação para gravar um MP4.');
      view.intent.textContent = '';
      return;
    }
    view.download.disabled = false;
    setReason(view.download, '');
    view.intent.textContent = downloaded
      ? 'Os segmentos já estão em cache; vai apenas gravar o MP4.'
      : (exportToo
          ? 'Vai baixar os segmentos e gravar um MP4 ao terminar.'
          : 'Vai baixar os segmentos para o cache local.');
  }

  async function start(operation, trigger) {
    await withBusy(trigger, 'Iniciando', async () => {
      try {
        const data = await context.request(operation, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(selection()),
        });
        view.jobResult.textContent = `${JOB_KIND[data.job.kind] || data.job.kind} iniciado.`;
        view.jobResult.className = 'ui-result ui-result--success';
        pollJob(data.job.id);
      } catch (error) {
        view.jobResult.textContent = error.message;
        view.jobResult.className = 'ui-result ui-result--danger';
      }
    });
  }

  // O progresso do job iniciado aqui aparece aqui -- feedback no controle que
  // disparou a acao, nao num painel do outro lado do app.
  async function pollJob(jobId) {
    if (timer) { clearTimeout(timer); timer = null; }
    try {
      const data = await context.request(`jobs/${jobId}`);
      const job = data.job;
      const [label] = JOB_STATE[job.state] || [job.state];
      view.jobResult.textContent = `${label} · ${job.completed}/${job.total || '?'}`;
      if (ACTIVE_STATES.includes(job.state)) {
        timer = setTimeout(() => pollJob(jobId), 1000);
        return;
      }
      view.jobResult.className = `ui-result ui-result--${job.state === 'failed' ? 'danger' : 'success'}`;
      await loadAvailability();
      await context.notifyChanged(item.id);
    } catch (error) { /* o job continua no painel de Atividade */ }
  }

  if (playable) {
    view.exportToo.onchange = syncIntent;
    view.download.onclick = () => start(view.exportToo.checked ? 'download-export' : 'download', view.download);

    view.clearCache.onclick = async () => {
      const confirmed = await context.confirm({
        title: 'Remover o cache desta mídia?',
        body: 'Os segmentos baixados serão apagados e precisarão ser baixados de novo. '
            + 'Um MP4 já exportado não é afetado.',
        confirmLabel: 'Remover', danger: true,
      });
      if (!confirmed) return;
      await withBusy(view.clearCache, 'Removendo', async () => {
        try {
          const result = await context.request('cache/cleanup', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode: 'media', media_ids: [item.id] }),
          });
          const skipped = result.skipped ? ` · ${result.skipped} não puderam ser removidos` : '';
          view.clearResult.textContent =
            `${result.removed} arquivo(s) removido(s) · ${formatBytes(result.bytes)} liberados${skipped}`;
          view.clearResult.className = `ui-result ui-result--${result.skipped ? 'warning' : 'success'}`;
          await loadAvailability();
          await context.notifyChanged(item.id);
        } catch (error) {
          view.clearResult.textContent = error.message;
          view.clearResult.className = 'ui-result ui-result--danger';
        }
      });
    };

    view.subtitleUpload.onclick = () => withBusy(view.subtitleUpload, 'Enviando', async () => {
      const file = view.subtitleFile.files[0];
      const language = view.subtitleLanguage.value.trim();
      if (!file || !language) {
        view.subtitleResult.textContent = 'Escolha um arquivo e informe o idioma.';
        view.subtitleResult.className = 'ui-result ui-result--warning';
        return;
      }
      try {
        const query = new URLSearchParams({
          media_id: item.id, language, label: view.subtitleLabel.value.trim(), filename: file.name,
        });
        await context.request(`subtitles/upload?${query}`, {
          method: 'POST', headers: { 'Content-Type': file.type || 'text/plain' }, body: file,
        });
        view.subtitleResult.textContent = 'Legenda adicionada.';
        view.subtitleResult.className = 'ui-result ui-result--success';
        await loadAvailability();
      } catch (error) {
        view.subtitleResult.textContent = error.message;
        view.subtitleResult.className = 'ui-result ui-result--danger';
      }
    });
  }

  try {
    await loadAvailability();
  } catch (error) {
    render(view.status, resultLine({ message: error.message || 'Disponibilidade indisponível.', tone: 'danger' }));
  }

  return { cleanup() { if (timer) clearTimeout(timer); context.root.replaceChildren(); } };
}
