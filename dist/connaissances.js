// Renatura · knowledge base page: inspect, search, add, disable and delete RAG documents (/api/assistant/knowledge/*).
import { $, esc, fmt } from './extensions-common.js';

const API = 'api/assistant/knowledge';
const ORIGIN = { user: 'Ajout équipe', methode: 'Méthode', corpus: 'Corpus' };
const state = { offset: 0, limit: 25, total: 0, needsKey: false };

const headers = () => (state.needsKey && $('#k-key').value ? { 'X-Knowledge-Key': $('#k-key').value } : {});
async function call(path, opts = {}) {
  const r = await fetch(`${API}${path}`, { ...opts, headers: { ...(opts.headers || {}), ...headers() } });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
  return body;
}
function fail(e) { $('#status').hidden = false; $('#status').textContent = e.message; }

async function status() {
  const s = await call('/status');
  state.needsKey = s.edit_requires_key;
  $('#k-key').hidden = $('#k-key-label').hidden = !s.edit_requires_key;
  const o = s.origins || {};
  const n = k => fmt(o[k]?.documents || 0) + ' doc. · ' + fmt(o[k]?.passages || 0) + ' passages';
  $('#config').innerHTML = [
    ['Recherche', s.mode], ['Plongements (Hugging Face)', s.model], ['LLM', `${s.llm.provider} · ${s.llm.model}`],
    ['Données envoyées hors de la machine', s.llm.local ? 'non' : 'oui (fournisseur distant)'],
    ['Corpus Normandie', n('corpus')], ['Méthode Renatura', n('methode')], ['Ajouts de l’équipe', n('user')],
    ['Stockage', s.store]].map(([k, v]) => `<span>${esc(k)}</span><b>${esc(v)}</b>`).join('')
    + (s.model_error ? `<span style="grid-column:1/-1;color:var(--bad)">Modèle indisponible : ${esc(s.model_error)}</span>` : '');
}

async function documents() {
  const p = new URLSearchParams({ q: $('#filter').value.trim(), origin: $('#origin').value, limit: state.limit, offset: state.offset });
  const d = await call(`/documents?${p}`);
  state.total = d.total;
  $('#count').textContent = `${fmt(d.total)} document(s)`;
  $('#page').textContent = d.total ? `${state.offset + 1}–${Math.min(state.offset + state.limit, d.total)} / ${fmt(d.total)}` : '';
  $('#prev').disabled = state.offset === 0;
  $('#next').disabled = state.offset + state.limit >= d.total;
  $('#docs').innerHTML = d.documents.map(x => `<tr class="${x.enabled ? '' : 'off'}">
      <td><b>${esc(x.title)}</b><br><span class="micro">${esc(x.category || '')}${x.source ? ' · ' + esc(x.source.replace(/^corpus:/, '')) : ''}</span></td>
      <td><span class="tag ${esc(x.origin)}">${esc(ORIGIN[x.origin] || x.origin)}</span></td>
      <td class="n">${fmt(x.n_chunks)}</td>
      <td class="act"><div class="acts"><button data-view="${esc(x.id)}">Voir</button>
        <button data-toggle="${esc(x.id)}" data-on="${x.enabled ? 0 : 1}">${x.enabled ? 'Désactiver' : 'Activer'}</button>
        <button class="danger" data-del="${esc(x.id)}" data-title="${esc(x.title)}">Supprimer</button></div></td></tr>`).join('')
    || '<tr><td colspan="4">Aucun document. Lancer « python -m pipeline.assistant.knowledge build » pour importer le corpus.</td></tr>';
  document.querySelectorAll('[data-view]').forEach(b => b.onclick = () => view(b.dataset.view).catch(fail));
  document.querySelectorAll('[data-toggle]').forEach(b => b.onclick = () =>
    call(`/documents/${b.dataset.toggle}?enabled=${b.dataset.on === '1'}`, { method: 'PATCH' }).then(refresh).catch(fail));
  document.querySelectorAll('[data-del]').forEach(b => b.onclick = () => {
    if (!confirm(`Supprimer définitivement « ${b.dataset.title} » ? (Désactiver suffit pour ne plus l’utiliser.)`)) return;
    call(`/documents/${b.dataset.del}`, { method: 'DELETE' }).then(refresh).catch(fail);
  });
}

async function view(id) {
  const d = await call(`/documents/${id}`);
  $('#v-title').textContent = d.title;
  $('#v-meta').textContent = `${ORIGIN[d.origin] || d.origin} · ${d.category || ''} · ${d.n_chunks} passage(s) · ${d.enabled ? 'actif' : 'désactivé'}${d.source ? ' · ' + d.source : ''}`;
  $('#v-text').textContent = d.chunks.join('\n\n──────────\n\n');
  $('#viewer').showModal();
}

async function search(e) {
  e?.preventDefault();
  const q = $('#q').value.trim();
  if (!q) return;
  $('#hits').innerHTML = '<p class="micro">Recherche…</p>';
  const r = await call(`/search?q=${encodeURIComponent(q)}&k=5`);
  $('#hits').innerHTML = r.results.map((h, i) => `<div class="hit"><b>${i + 1}. ${esc(h.titre)}</b>
      <span class="tag ${esc(h.origine)}">${esc(ORIGIN[h.origine] || h.origine)}</span> <span class="micro">score ${h.score} · ${esc(h.mode)}</span>
      <pre>${esc(h.passage)}</pre></div>`).join('') || '<p class="micro">Aucun passage.</p>';
}

$('#add-form').addEventListener('submit', async e => {
  e.preventDefault();
  const body = new FormData();
  body.append('title', $('#k-title').value.trim());
  body.append('source', $('#k-source').value.trim());
  body.append('category', $('#k-cat').value);
  body.append('text', $('#k-text').value);
  if ($('#k-file').files[0]) body.append('file', $('#k-file').files[0]);
  $('#add-btn').disabled = true;
  $('#add-msg').textContent = 'Découpage et calcul des plongements…';
  try {
    const d = await call('/documents', { method: 'POST', body });
    $('#add-msg').textContent = `Ajouté : « ${d.title} » · ${d.n_chunks} passage(s). L’assistant peut l’utiliser dès maintenant.`;
    e.target.reset();
    refresh();
  } catch (err) {
    $('#add-msg').textContent = 'Erreur : ' + err.message;
  } finally {
    $('#add-btn').disabled = false;
  }
});
$('#search-form').addEventListener('submit', e => search(e).catch(fail));
let t;
$('#filter').addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => { state.offset = 0; documents().catch(fail); }, 250); });
$('#origin').addEventListener('change', () => { state.offset = 0; documents().catch(fail); });
$('#prev').addEventListener('click', () => { state.offset = Math.max(0, state.offset - state.limit); documents().catch(fail); });
$('#next').addEventListener('click', () => { state.offset += state.limit; documents().catch(fail); });

function refresh() { return Promise.all([status(), documents()]).catch(fail); }
refresh();
