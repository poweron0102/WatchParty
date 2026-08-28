function button(label) {
  const value = document.createElement('button');
  value.type = 'button'; value.textContent = label;
  value.className = 'bg-brand text-white px-3 py-2 rounded-md disabled:opacity-50';
  return value;
}

export async function mount(context) {
  let items = [], parentId = null, timer = null;
  const description = document.createElement('p');
  description.className = 'text-sm mb-3'; description.style.color = 'var(--text-secondary)';
  description.textContent = 'Grave pôsteres 2:3 e thumbnails 16:9 diretamente em .previews.';
  const select = document.createElement('select');
  select.className = 'w-full bg-input border border-input rounded-md px-3 py-2 mb-3';
  const upload = document.createElement('input'); upload.type = 'file'; upload.accept = 'image/*'; upload.className = 'block w-full mb-3';
  const variant = document.createElement('select'); variant.className = select.className;
  [['thumbnail', 'Thumbnail 16:9'], ['poster', 'Pôster 2:3']].forEach(([value, label]) => {
    const option = document.createElement('option'); option.value = value; option.textContent = label; variant.appendChild(option);
  });
  const actions = document.createElement('div'); actions.className = 'flex flex-wrap gap-2';
  const uploadButton = button('Enviar imagem'); const generateButton = button('Gerar thumbnail');
  const missingButton = button('Gerar ausentes nesta pasta'); const overwriteButton = button('Regenerar recursivamente');
  actions.append(uploadButton, generateButton, missingButton, overwriteButton);
  const jobStatus = document.createElement('p'); jobStatus.className = 'text-sm mt-3'; jobStatus.style.color = 'var(--text-secondary)';
  context.root.replaceChildren(description, select, variant, upload, actions, jobStatus);

  function selected() { return items.find(item => item.id === select.value); }
  function refreshSelection() {
    select.replaceChildren();
    for (const item of items) {
      const option = document.createElement('option'); option.value = item.id; option.textContent = item.title; select.appendChild(option);
    }
    const playable = selected()?.entry_type === 'playable';
    generateButton.disabled = !playable; uploadButton.disabled = !items.length;
  }
  async function refreshJobs() {
    const data = await context.request('previews/status');
    const active = data.jobs?.filter(job => !['completed', 'failed'].includes(job.state));
    const latest = data.jobs?.at(-1);
    if (latest) jobStatus.textContent = `Job ${latest.state}: ${latest.completed}/${latest.total}, ${latest.created} criadas, ${latest.failed} falhas.`;
    if (active?.length) timer = setTimeout(() => refreshJobs().catch(() => {}), 1000);
  }
  uploadButton.onclick = async () => {
    const item = selected(), file = upload.files[0];
    if (!item || !file) { context.showStatus('Selecione um item e uma imagem.', 'error'); return; }
    try {
      const query = new URLSearchParams({media_id:item.id, entry_type:item.entry_type, variant:variant.value});
      await context.request(`previews/upload?${query}`, {method:'POST', headers:{'Content-Type':file.type || 'application/octet-stream'}, body:file});
      context.showStatus('Imagem atualizada.'); await context.refresh();
    } catch (error) { context.showStatus(error.message, 'error'); }
  };
  generateButton.onclick = async () => {
    const item = selected(); if (!item) return;
    try {
      await context.request('previews/generate', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({media_id:item.id, overwrite:true})});
      context.showStatus('Thumbnail atualizada.'); await context.refresh();
    } catch (error) { context.showStatus(error.message, 'error'); }
  };
  async function bulk(overwrite) {
    if (overwrite && !confirm('Regenerar thumbnails recursivamente e substituir as existentes?')) return;
    try {
      await context.request('previews/generate-bulk', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({parent_id:parentId || '', overwrite})});
      context.showStatus('Geração iniciada.'); await refreshJobs();
    } catch (error) { context.showStatus(error.message, 'error'); }
  }
  missingButton.onclick = () => bulk(false); overwriteButton.onclick = () => bulk(true);
  refreshSelection(); refreshJobs().catch(() => {});
  return {
    catalogRendered(state) { items = state.items; parentId = state.parentId; refreshSelection(); },
    cleanup() { if (timer) clearTimeout(timer); context.root.replaceChildren(); },
  };
}
