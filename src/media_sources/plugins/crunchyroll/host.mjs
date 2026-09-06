function el(tag, text, className = '') {
  const value = document.createElement(tag); if (text != null) value.textContent = text; if (className) value.className = className; return value;
}
function button(text) { return el('button', text, 'ui-btn ui-btn--secondary'); }
// O host so conhece o valor cru do backend e escreveria "series · Crunchyroll"
// no cabecalho.  Quem sabe traduzir e o plugin, e setHeader e como ele alcanca
// o elemento.
const KIND = { series: 'Série', season: 'Temporada', episode: 'Episódio', movie: 'Filme' };

function formatBytes(value) {
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']; let index = 0, number = Number(value || 0);
  while (number >= 1024 && index < units.length - 1) { number /= 1024; index++; }
  return `${number.toFixed(index ? 2 : 0)} ${units[index]}`;
}

export async function mount(context) {
  let inventory = [], defaults = {}, presentation = null, catalogItems = [], currentParent = null, timer = null;
  const intro = el('p', 'Cache, downloads, legendas e exportações pertencem somente a este plugin.', 'ui-result');
    const mediaSelect = el('select', null, 'ui-input');
  const summary = el('p', '', 'ui-result');
  const storage = el('p', '', 'ui-result');
  const refreshCatalog = button('Atualizar catálogo'); const reportButton = button('Relatório de falhas'); const report = el('p', '', 'ui-result');
  const refresh = button('Atualizar inventário'); const inspect = button('Carregar faixas');
  const topActions = el('div', null, 'plugin-row'); topActions.append(refresh, inspect, refreshCatalog, reportButton);
  const tracks = el('div', null, 'plugin-stack');
  const download = button('Iniciar download'); const exportButton = button('Salvar como MP4');
  const mediaActions = el('div', null, 'plugin-row'); mediaActions.append(download, exportButton);

  const subtitleTitle = el('h3', 'Adicionar legenda', 'ui-section-title');
  const subtitleFile = el('input'); subtitleFile.type = 'file'; subtitleFile.accept = '.ass,.srt,.vtt'; subtitleFile.className = 'ui-input';
  const subtitleLanguage = el('input'); subtitleLanguage.placeholder = 'Idioma, ex.: pt-BR'; subtitleLanguage.className = 'ui-input';
  const subtitleLabel = el('input'); subtitleLabel.placeholder = 'Rótulo opcional'; subtitleLabel.className = subtitleLanguage.className;
  const subtitleUpload = button('Enviar legenda');

  const cleanupTitle = el('h3', 'Limpeza do cache', 'ui-section-title');
  const cleanupMode = el('select', null, mediaSelect.className);
  [['exported','Mídias com MP4 exportado'],['quality','Qualidade de vídeo'],['partial','Parciais antigas'],['media','Mídia selecionada'],['collection','Série/temporada atual'],['orphans','Órfãos'],['all','Todo o cache de segmentos']].forEach(([value,label]) => {
    const option = el('option', label); option.value = value; cleanupMode.appendChild(option);
  });
  const cleanupValue = el('input'); cleanupValue.placeholder = 'Altura (480) ou dias (30)'; cleanupValue.className = subtitleLanguage.className;
  const cleanupPreview = button('Simular limpeza'); const cleanupRun = button('Executar limpeza'); cleanupRun.disabled = true;
  const cleanupActions = el('div', null, 'plugin-row'); cleanupActions.append(cleanupPreview, cleanupRun);
  const cleanupResult = el('p', '', 'ui-result');
  const preferencesTitle = el('h3', 'Preferências padrão', 'ui-section-title');
  const preferences = el('div', 'Qualidade, áudio e legendas são preferências para novos jobs.', 'ui-result');
  const preferenceQuality = el('input'); preferenceQuality.className = subtitleLanguage.className; preferenceQuality.placeholder = 'Qualidade máxima';
  const preferenceAudio = el('input'); preferenceAudio.className = subtitleLanguage.className; preferenceAudio.placeholder = 'Áudios (separados por vírgula)';
  const preferenceSubtitle = el('input'); preferenceSubtitle.className = subtitleLanguage.className; preferenceSubtitle.placeholder = 'Legendas (separadas por vírgula)';
  const savePreferences = button('Salvar preferências');

  const jobsTitle = el('h3', 'Jobs desta execução', 'ui-section-title');
  const jobs = el('div', null, 'plugin-stack');
  context.root.replaceChildren(intro, storage, mediaSelect, summary, report, topActions, tracks, mediaActions,
    subtitleTitle, subtitleFile, subtitleLanguage, subtitleLabel, subtitleUpload,
    cleanupTitle, cleanupMode, cleanupValue, cleanupActions, cleanupResult, preferencesTitle, preferences,
    preferenceQuality, preferenceAudio, preferenceSubtitle, savePreferences, jobsTitle, jobs);

  function mediaId() { return mediaSelect.value; }
  function populateMedia() {
    const previous = mediaSelect.value; mediaSelect.replaceChildren();
    const all = new Map(inventory.map(item => [item.media_id, item.title]));
    for (const item of catalogItems.filter(item => item.entry_type === 'playable')) if (!all.has(item.id)) all.set(item.id, item.title);
    for (const [id, title] of all) { const option = el('option', title); option.value = id; mediaSelect.appendChild(option); }
    if ([...mediaSelect.options].some(option => option.value === previous)) mediaSelect.value = previous;
    updateSummary();
  }
  function updateSummary() {
    const item = inventory.find(value => value.media_id === mediaId());
    summary.textContent = item ? `${item.state} · ${Math.round(item.coverage * 100)}% indexado · ${formatBytes(item.cached_bytes)} · ${item.exports.length} exportação(ões)` : 'A mídia ainda não possui segmentos indexados.';
  }
  function isDefaultLanguage(language, configured) { return configured.some(value => value === '*' || value.toLowerCase() === String(language || '').toLowerCase()); }
  function renderTracks() {
    tracks.replaceChildren();
    if (!presentation) { tracks.appendChild(el('p', 'Carregue as faixas da mídia selecionada.')); return; }
    for (const track of presentation.tracks) {
      const group = el('fieldset', null, 'plugin-group');
      const legend = el('legend', `${track.kind} · ${track.label || track.language || track.id}`, ''); group.appendChild(legend);
      for (const rep of track.representations) {
        const label = el('label', null, 'plugin-row'); const input = el('input');
        input.type = track.kind === 'video' ? 'radio' : 'checkbox'; input.name = track.kind === 'video' ? 'cr-video-rep' : `cr-${track.kind}`;
        input.dataset.track = track.id; input.dataset.rep = rep.id; input.dataset.kind = track.kind;
        if (track.kind === 'video') input.checked = rep.id === presentation.canonical_video_representation;
        else if (track.kind === 'audio') input.checked = isDefaultLanguage(track.language, defaults.audio_languages || []);
        else input.checked = isDefaultLanguage(track.language, defaults.subtitle_languages || []);
        const dimensions = rep.height ? `${rep.height}p` : `${Math.round((rep.bandwidth || 0) / 1000)} kbps`;
        label.append(input, document.createTextNode(dimensions)); group.appendChild(label);
      }
      tracks.appendChild(group);
    }
  }
  function selectionPayload() {
    const checked = [...tracks.querySelectorAll('input:checked')];
    return {media_id:mediaId(), video_representation:checked.find(value => value.dataset.kind === 'video')?.dataset.rep,
      audio_tracks:checked.filter(value => value.dataset.kind === 'audio').map(value => value.dataset.track),
      subtitle_tracks:checked.filter(value => value.dataset.kind === 'text').map(value => value.dataset.track)};
  }
  async function loadInventory() {
    const data = await context.request('cache'); inventory = data.media; defaults = data.defaults; storage.textContent = `Armazenamento: ${formatBytes(data.storage?.cached_bytes || 0)} · ${data.storage?.media_count || 0} mídia(s) · ${data.storage?.export_count || 0} exportação(ões)`; populateMedia(); renderJobs(data.jobs);
    preferenceQuality.value = defaults.video_quality || '';
    preferenceAudio.value = (defaults.audio_languages || []).join(',');
    preferenceSubtitle.value = (defaults.subtitle_languages || []).join(',');
  }
  async function loadPresentation() {
    if (!mediaId()) return; presentation = await context.request(`presentation?${new URLSearchParams({media_id:mediaId()})}`); renderTracks();
  }
  function renderJobs(values) {
    jobs.replaceChildren();
    for (const job of values) {
      const row = el('div', null, 'plugin-row');
      row.appendChild(el('span', `${job.kind}: ${job.state} · ${job.completed}/${job.total}${job.message ? ` · ${job.message}` : ''}${job.error ? ` · ${job.error}` : ''}`));
      if (['queued','running','paused'].includes(job.state)) {
        const operation = job.state === 'paused' ? 'resume' : 'pause'; const toggle = button(operation === 'pause' ? 'Pausar' : 'Retomar'); const cancel = button('Cancelar');
        toggle.onclick = async () => { await context.request(`jobs/${job.id}/${operation}`, {method:'POST'}); await pollJobs(); };
        cancel.onclick = async () => { await context.request(`jobs/${job.id}/cancel`, {method:'POST'}); await pollJobs(); };
        row.append(toggle, cancel);
      }
      jobs.appendChild(row);
    }
    if (!values.length) jobs.appendChild(el('p', 'Nenhum job nesta execução.'));
    if (values.some(job => ['queued','running','paused'].includes(job.state))) timer = setTimeout(pollJobs, 1000);
  }
  async function pollJobs() {
    const data = await context.request('jobs');
    renderJobs(data.jobs);
    if (data.jobs.some(job => ['queued','running','paused'].includes(job.state))) return;
    await loadInventory();
    // O estado de cache das midias mudou; os cards precisam saber.
    await context.notifyChanged();
  }
  async function start(action) {
    if (!presentation || presentation.media_id !== mediaId()) await loadPresentation();
    const data = await context.request(action, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(selectionPayload())});
    context.showStatus(`${data.job.kind} iniciado.`); await pollJobs();
  }
  refresh.onclick = () => loadInventory().catch(error => context.showStatus(error.message, 'error'));
  savePreferences.onclick = async () => { try { await context.request('preferences', {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({video_quality:preferenceQuality.value.trim(), audio_languages:preferenceAudio.value.split(',').map(value => value.trim()).filter(Boolean), subtitle_languages:preferenceSubtitle.value.split(',').map(value => value.trim()).filter(Boolean)})}); context.showStatus('Preferências salvas.'); } catch (error) { context.showStatus(error.message, 'error'); } };
  refreshCatalog.onclick = async () => { try { await context.request('catalog/refresh', {method:'POST'}); context.showStatus('Catálogo atualizado.'); await context.refresh(); } catch (error) { context.showStatus(error.message, 'error'); } };
  reportButton.onclick = async () => { try { const data = await context.request('jobs/report'); const count = data.jobs.reduce((total, job) => total + job.failures.length, 0); report.textContent = count ? `${count} falha(s) registradas.` : 'Nenhuma falha registrada nesta execução.'; } catch (error) { context.showStatus(error.message, 'error'); } };
  inspect.onclick = () => loadPresentation().catch(error => context.showStatus(error.message, 'error'));
  mediaSelect.onchange = () => { presentation = null; updateSummary(); renderTracks(); };
  download.onclick = () => start('download').catch(error => context.showStatus(error.message, 'error'));
  exportButton.onclick = () => start('export-mp4').catch(error => context.showStatus(error.message, 'error'));
  subtitleUpload.onclick = async () => {
    const file = subtitleFile.files[0]; if (!file || !mediaId() || !subtitleLanguage.value.trim()) { context.showStatus('Selecione mídia, arquivo e idioma.', 'error'); return; }
    const query = new URLSearchParams({media_id:mediaId(), language:subtitleLanguage.value.trim(), label:subtitleLabel.value.trim(), filename:file.name});
    try { await context.request(`subtitles/upload?${query}`, {method:'POST', headers:{'Content-Type':file.type || 'text/plain'}, body:file}); context.showStatus('Legenda adicionada.'); await loadPresentation(); }
    catch (error) { context.showStatus(error.message, 'error'); }
  };
  function cleanupPayload() {
    const mode = cleanupMode.value, payload = {mode};
    if (mode === 'quality') payload.height = Number(cleanupValue.value);
    if (mode === 'partial') payload.older_than_days = Number(cleanupValue.value || 30);
    if (mode === 'media') payload.media_ids = [mediaId()];
    if (mode === 'collection') payload.parent_id = currentParent || '';
    return payload;
  }
  cleanupPreview.onclick = async () => {
    try { const result = await context.request('cache/cleanup-preview', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(cleanupPayload())});
      cleanupResult.textContent = `${result.count} arquivo(s), ${formatBytes(result.bytes)}, ${result.media?.length || 0} mídia(s).`; cleanupRun.disabled = !result.count; }
    catch (error) { context.showStatus(error.message, 'error'); }
  };
  cleanupRun.onclick = async () => {
    const confirmed = await context.confirm({
      title: 'Executar a limpeza simulada?',
      body: 'Os arquivos de cache removidos terão de ser baixados novamente.',
      confirmLabel: 'Limpar', danger: true,
    });
    if (!confirmed) return;
    try { const result = await context.request('cache/cleanup', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(cleanupPayload())});
      context.showStatus(`${result.removed} arquivo(s) removido(s), ${formatBytes(result.bytes)} recuperados.`); cleanupRun.disabled = true; await loadInventory(); }
    catch (error) { context.showStatus(error.message, 'error'); }
  };
  renderTracks(); await loadInventory();
  return {
    catalogRendered(state) { catalogItems = state.items; currentParent = state.parentId; populateMedia(); },
    cleanup() { if (timer) clearTimeout(timer); context.root.replaceChildren(); },
  };
}

// The host owns the modal and the favorite control.  This hook owns only
// Crunchyroll-specific availability and operations.
export function titleAction(entity, actions) { return actions.openInspector(entity); }

export async function mountInspector(context) {
  const item = context.entity;
  const root = context.root;
  const kind = item.entity_kind || item.media_kind || item.id?.split(':', 1)[0];
  context.setHeader({ title: item.title, subtitle: `${KIND[kind] || 'Mídia'} · ${context.source?.label || 'Crunchyroll'}` });
  const heading = el('p', `${item.title} · ${item.entity_kind || item.media_kind || 'mídia'}`, 'ui-section-title');
  const status = el('p', 'Carregando disponibilidade…', 'ui-result');
  const actions = el('div', null, 'plugin-row');
  const download = button('Baixar para cache');
  const save = button('Salvar como MP4');
  const downloadSave = button('Baixar e salvar como MP4');
  actions.append(download, save, downloadSave);
  root.replaceChildren(heading, status, actions);

  let presentation = null;
  const payload = () => ({media_id: item.id, video_representation: presentation?.canonical_video_representation,
    audio_tracks: (presentation?.tracks || []).filter(track => track.kind === 'audio' && track.default).map(track => track.id),
    subtitle_tracks: []});
  try {
    if (item.entry_type === 'playable') {
      presentation = await context.request(`presentation?${new URLSearchParams({media_id:item.id})}`);
      const inventory = await context.request('cache');
      const cached = inventory.media?.find(value => value.media_id === item.id);
      const coverage = cached ? Math.round(cached.coverage * 100) : 0;
      status.textContent = `${cached?.state || 'disponível remotamente'} · ${coverage}% em cache`;
      save.disabled = cached?.state !== 'offline' && cached?.state !== 'exported';
      download.onclick = () => start('download');
      save.onclick = () => start('export-mp4');
      downloadSave.onclick = () => start('download-export');
    } else {
      // O agregado vem do backend, escopado por parent_id.  Antes era feito
      // aqui com `media_id.startsWith('episode:')` sobre o inventario inteiro,
      // o que contava os episodios de TODAS as series e exibia o numero como
      // se fosse desta.  A hierarquia mora no banco.
      const summary = await context.request(`cache/summary?${new URLSearchParams({ parent_id: item.id })}`);
      const complete = summary.offline + summary.exported;
      status.textContent = summary.total
        ? `${complete} baixado(s) · ${summary.partial} parcial(is) · ${summary.empty} sem cache · ${summary.total} episódio(s)`
        : 'Nenhum episódio catalogado nesta coleção.';
      download.disabled = true; save.disabled = true; downloadSave.disabled = true;
    }
  } catch (error) { status.textContent = error.message || 'Disponibilidade desatualizada (offline).'; }

  async function start(operation) {
    try {
      const data = await context.request(operation, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload())});
      context.showStatus(`${data.job.kind} iniciado.`);
    } catch (error) { context.showStatus(error.message, 'error'); }
  }
  return {cleanup() { root.replaceChildren(); }};
}
