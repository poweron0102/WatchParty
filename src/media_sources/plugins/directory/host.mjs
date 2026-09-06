/* Ferramentas da origem "pasta local": geracao e envio de previas.
 *
 * O modulo e servido em /host/{source_id}/module.js, entao o import precisa
 * ser absoluto -- um caminho relativo resolveria para
 * /host/{source_id}/modules/ui.js, que nao existe.
 */
import { html, render, section, field, button, withBusy, inlineConfirm, resultLine }
  from '/modules/ui.js';

export async function mount(context) {
  let items = [], parentId = null, timer = null;

  const view = render(context.root, html`
    ${section({
      title: 'Prévias de imagem',
      description: 'Grave pôsteres 2:3 e thumbnails 16:9 diretamente em .previews.',
      body: html`
        ${field({ label: 'Item', control: html`<select data-ref="media"></select>` })}
        ${field({
          label: 'Formato',
          control: html`<select data-ref="variant">
            <option value="thumbnail">Thumbnail 16:9</option>
            <option value="poster">Pôster 2:3</option>
          </select>`,
        })}
        ${field({
          label: 'Arquivo de imagem',
          control: html`<input data-ref="upload" type="file" accept="image/*">`,
          hint: 'A imagem é reenquadrada para o formato escolhido.',
        })}
        <div class="plugin-row">
          ${button({ label: 'Enviar imagem', ref: 'send', variant: 'primary' })}
          ${button({ label: 'Gerar thumbnail', ref: 'generate' })}
        </div>
      `,
    })}
    ${section({
      title: 'Geração em lote',
      description: 'Percorre a pasta aberta no Explorador.',
      body: html`
        <div class="plugin-row">
          ${button({ label: 'Gerar as ausentes', ref: 'missing' })}
          ${button({ label: 'Regenerar recursivamente', ref: 'overwrite', variant: 'danger' })}
        </div>
        <div data-ref="confirm"></div>
        ${resultLine({ message: 'Nenhuma geração nesta execução.', ref: 'jobs' })}
      `,
    })}
  `);

  function selected() { return items.find(item => item.id === view.media.value); }

  function refreshSelection() {
    const previous = view.media.value;
    view.media.replaceChildren();
    for (const item of items) {
      const option = document.createElement('option');
      option.value = item.id;
      option.textContent = item.title;
      view.media.appendChild(option);
    }
    if ([...view.media.options].some(option => option.value === previous)) view.media.value = previous;
    view.media.disabled = !items.length;
    view.generate.disabled = selected()?.entry_type !== 'playable';
    view.send.disabled = !items.length;
  }

  async function refreshJobs() {
    const data = await context.request('previews/status');
    const active = (data.jobs || []).filter(job => !['completed', 'failed'].includes(job.state));
    const latest = data.jobs?.at(-1);
    if (latest) {
      view.jobs.textContent =
        `${latest.state}: ${latest.completed}/${latest.total} · ${latest.created} criada(s) · ${latest.failed} falha(s).`;
    }
    if (active.length) timer = setTimeout(() => refreshJobs().catch(() => {}), 1000);
  }

  view.send.onclick = () => withBusy(view.send, 'Enviando', async () => {
    const item = selected(), file = view.upload.files[0];
    if (!item || !file) { context.showStatus('Selecione um item e uma imagem.', 'error'); return; }
    try {
      const query = new URLSearchParams({ media_id: item.id, entry_type: item.entry_type, variant: view.variant.value });
      await context.request(`previews/upload?${query}`, {
        method: 'POST', headers: { 'Content-Type': file.type || 'application/octet-stream' }, body: file,
      });
      context.showStatus('Imagem atualizada.');
      await context.refresh();
    } catch (error) { context.showStatus(error.message, 'error'); }
  });

  view.generate.onclick = () => withBusy(view.generate, 'Gerando', async () => {
    const item = selected();
    if (!item) return;
    try {
      await context.request('previews/generate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ media_id: item.id, overwrite: true }),
      });
      context.showStatus('Thumbnail atualizada.');
      await context.refresh();
    } catch (error) { context.showStatus(error.message, 'error'); }
  });

  async function bulk(overwrite, trigger) {
    if (overwrite) {
      const confirmed = await inlineConfirm(view.confirm, {
        title: 'Regenerar recursivamente?',
        body: 'As thumbnails existentes desta pasta e das subpastas serão substituídas.',
        confirmLabel: 'Regenerar',
      });
      if (!confirmed) return;
    }
    await withBusy(trigger, 'Iniciando', async () => {
      try {
        await context.request('previews/generate-bulk', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ parent_id: parentId || '', overwrite }),
        });
        context.showStatus('Geração iniciada.');
        await refreshJobs();
      } catch (error) { context.showStatus(error.message, 'error'); }
    });
  }

  view.missing.onclick = () => bulk(false, view.missing);
  view.overwrite.onclick = () => bulk(true, view.overwrite);

  refreshSelection();
  refreshJobs().catch(() => {});

  return {
    catalogRendered(state) { items = state.items; parentId = state.parentId; refreshSelection(); },
    cleanup() { if (timer) clearTimeout(timer); context.root.replaceChildren(); },
  };
}
