import { $, esc, fmt, partnerKey, setPartnerKey, loadJSON } from './extensions-common.js';

// Embedded in data.html (onglet « Photos nature ») : no site header, report height so the frame fits.
if (new URLSearchParams(location.search).has('embed')) {
  document.documentElement.classList.add('embedded');
  const report = () => parent.postMessage({ type: 'renatura-embed-height', height: document.documentElement.scrollHeight }, location.origin);
  new ResizeObserver(report).observe(document.body);
  addEventListener('load', report);
}

const API = '/api/nature';
const GROUP_FR = { birds: 'oiseaux', mammals: 'mammifères', fish: 'poissons', insects: 'insectes', amphibians: 'amphibiens', reptiles: 'reptiles',
  arachnids: 'arachnides', molluscs: 'mollusques', crustaceans: 'crustacés', flowering_plants: 'plantes à fleurs', ferns: 'fougères',
  conifers: 'conifères', mosses: 'mousses', other_plants: 'autres plantes', other_animalia: 'autres animaux', other_arthropods: 'autres arthropodes' };

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  const key = partnerKey();
  if (key) headers['X-Partner-Key'] = key;
  const r = await fetch(API + path, { ...options, headers });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
  return body;
}

// ---------- tabs
document.querySelectorAll('[data-tab]').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('[data-tab]').forEach(x => x.setAttribute('aria-selected', String(x === b)));
  document.querySelectorAll('[data-panel]').forEach(p => { p.hidden = p.dataset.panel !== b.dataset.tab; });
  ({ validate: loadQueue, evidence: loadEvidence, model: loadModel })[b.dataset.tab]?.();
  setTimeout(() => { pick.invalidateSize(); evmap?.invalidateSize(); }, 50);
}));

// ---------- service check
api('/health').then(h => {
  if (!h.model_ready) { const s = $('#service'); s.hidden = false; s.textContent = `Modèle pas encore disponible (${h.model_error || 'entraînement en cours'}).`; }
}).catch(() => {
  const s = $('#service'); s.hidden = false;
  s.innerHTML = 'Service photo injoignable. Lancer : <code>.venv-normandie/bin/python -m uvicorn pipeline.nature.server:app --port 8090</code> puis ouvrir <code>http://localhost:8090/photos-normandie.html</code>.';
});

// ---------- upload
$('#key').value = partnerKey();
$('#key').addEventListener('change', e => setPartnerKey(e.target.value.trim()));
const pick = L.map('pickmap', { preferCanvas: true }).setView([49.1, 0.0], 7);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18, attribution: '© OpenStreetMap' }).addTo(pick);
let marker = null;
pick.on('click', e => {
  $('#lat').value = e.latlng.lat.toFixed(5); $('#lon').value = e.latlng.lng.toFixed(5);
  marker ? marker.setLatLng(e.latlng) : (marker = L.marker(e.latlng).addTo(pick));
});

$('#send').addEventListener('click', async () => {
  const file = $('#file').files[0];
  if (!file) return show('#result', '<div class="error">Choisir une photo.</div>');
  setPartnerKey($('#key').value.trim());
  const fd = new FormData();
  fd.append('file', file);
  if ($('#lat').value && $('#lon').value) { fd.append('lat', $('#lat').value); fd.append('lon', $('#lon').value); }
  fd.append('licence', $('#licence').value); fd.append('consent_share', $('#consent').checked); fd.append('note', $('#note').value);
  $('#send').disabled = true; show('#result', '<p class="micro">Analyse…</p>');
  try {
    const r = await api('/photos', { method: 'POST', body: fd });
    show('#result', `<p><span class="chip ${r.status === 'auto' ? 'ok' : 'warn'}">${r.status === 'auto' ? 'confiance haute — à confirmer' : 'en attente de validation'}</span>
      maille <b>${esc(r.cell_id)}</b> · position ${esc(r.position_source)}${r.faces_blurred ? ` · ${r.faces_blurred} visage(s) flouté(s)` : ''}</p>
      ${top5(r.top5)}<p class="micro">Seuil d’acceptation automatique : ${r.auto_accept_threshold ? fmt(100 * r.auto_accept_threshold, 0) + ' %' : '—'} (précision ≥ 95 % sur la validation).</p>`);
  } catch (e) { show('#result', `<div class="error">${esc(e.message)}</div>`); }
  $('#send').disabled = false;
});

function top5(list) {
  return `<table class="data"><tr><th>Espèce proposée</th><th>Groupe</th><th>Probabilité</th></tr>${list.map(t => `<tr>
    <td><i>${esc(t.scientific_name)}</i><br><span class="micro">${esc(t.french_name)}</span></td><td>${esc(GROUP_FR[t.group_en] || t.group_en)}</td>
    <td><div class="bar"><i style="width:${(100 * t.probability).toFixed(0)}%"></i></div>${fmt(100 * t.probability, 1)} %</td></tr>`).join('')}</table>`;
}
const show = (sel, html) => { $(sel).innerHTML = html; };

// ---------- validation queue
$('#reload').addEventListener('click', loadQueue);
$('#qstatus').addEventListener('change', loadQueue);
async function loadQueue() {
  try {
    const rows = await api(`/photos?status=${$('#qstatus').value}`);
    $('#queue').innerHTML = rows.length ? rows.map(card).join('') : '<p class="muted">Aucune photo.</p>';
    document.querySelectorAll('[data-validate]').forEach(b => b.addEventListener('click', () => validate(b)));
  } catch (e) { $('#queue').innerHTML = `<div class="error">${esc(e.message)}</div>`; }
}
function card(r) {
  return `<div class="card"><img src="${esc(r.image)}" alt="photo ${esc(r.species)}" loading="lazy">
    <p><b><i>${esc(r.species)}</i></b> <span class="chip">${esc(r.status)}</span>${r.location_generalised ? '<span class="chip warn">position 10 km</span>' : ''}</p>
    <p class="micro">${esc(r.taken_at || r.created_at).slice(0, 16)} · maille ${esc(r.cell_id || '—')} · confiance ${fmt(100 * r.confidence, 0)} %
      ${r.validations.length ? '· validations : ' + r.validations.map(v => `${esc(v.partner)} (${esc(v.decision)})`).join(', ') : ''}</p>
    <select data-choice="${esc(r.id)}">${r.top5.map(t => `<option value="${esc(t.scientific_name)}">${esc(t.scientific_name)} — ${fmt(100 * t.probability, 0)} %</option>`).join('')}</select>
    <div class="row" style="margin-top:8px">
      <button class="primary" data-validate="confirm" data-id="${esc(r.id)}">Confirmer</button>
      <button class="secondary" data-validate="correct" data-id="${esc(r.id)}">Corriger (choix ci-dessus)</button>
      <button class="secondary" data-validate="reject" data-id="${esc(r.id)}">Rejeter</button></div></div>`;
}
async function validate(button) {
  const id = button.dataset.id, decision = button.dataset.validate;
  const species = document.querySelector(`[data-choice="${id}"]`).value;
  try { await api(`/photos/${id}/validate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision, species }) }); loadQueue(); }
  catch (e) { alertBox(e.message); }
}
const alertBox = m => { const s = $('#service'); s.hidden = false; s.className = 'error'; s.textContent = m; };

// ---------- evidence layer
let evmap = null, cellGeo = null;
async function loadEvidence() {
  const ev = await api('/evidence');
  $('#evsummary').innerHTML = `<div class="kpis"><div class="kpi"><b>${fmt(ev.meta.confirmed_photos)}</b><span>photos confirmées</span></div>
    <div class="kpi"><b>${fmt(ev.meta.cells)}</b><span>mailles documentées</span></div></div><p class="micro">${esc(ev.meta.rule)}</p>`;
  if (!evmap) {
    evmap = L.map('evmap', { preferCanvas: true }).setView([49.1, 0.0], 8);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18, attribution: '© OpenStreetMap' }).addTo(evmap);
  }
  const ids = Object.keys(ev.cells);
  if (!ids.length) return;
  cellGeo ??= await loadJSON('data/normandie/cells.geojson');
  const feats = cellGeo.features.filter(f => ev.cells[f.properties.id]);
  L.geoJSON({ type: 'FeatureCollection', features: feats }, {
    style: f => { const n = ev.cells[f.properties.id].species; return { weight: 0.5, color: '#173d31', fillOpacity: 0.75, fillColor: n >= 5 ? '#00441b' : n >= 2 ? '#74c476' : '#c7e9c0' }; },
    onEachFeature: (f, layer) => layer.on('click', () => {
      const c = ev.cells[f.properties.id];
      $('#evcell').innerHTML = `<h3>${esc(f.properties.commune || f.properties.id)}</h3><p>${c.photos} photos · ${c.species} espèces · effort ${c.effort_observer_days} observateur-jours</p>
        ${c.protected_species.length ? `<p>Protégées : ${c.protected_species.map(s => `<span class="chip ok">${esc(s)}</span>`).join('')}</p>` : ''}
        ${c.invasive_species.length ? `<p>Invasives : ${c.invasive_species.map(s => `<span class="chip bad">${esc(s)}</span>`).join('')}</p>` : ''}
        <p class="micro">Groupes : ${Object.entries(c.groups).map(([g, n]) => `${esc(GROUP_FR[g] || g)} ${n}`).join(' · ')}</p>`;
    }),
  }).addTo(evmap);
}

// ---------- model card
async function loadModel() {
  try {
    const m = await api('/model');
    const cal = m.calibration_auto_accept || {};
    $('#modelinfo').innerHTML = `<h2>Modèle ${esc(m.arch)} · ${fmt(m.classes)} espèces</h2>
      <div class="kpis"><div class="kpi"><b>${fmt(100 * m.test_top1, 1)} %</b><span>bonne espèce en 1re proposition (test)</span></div>
      <div class="kpi"><b>${fmt(100 * m.test_top5, 1)} %</b><span>bonne espèce parmi les 5 propositions</span></div>
      <div class="kpi"><b>${cal.threshold ? fmt(100 * cal.threshold, 0) + ' %' : '—'}</b><span>seuil d’acceptation auto (précision visée 95 %)</span></div>
      <div class="kpi"><b>${cal.test_coverage != null ? fmt(100 * cal.test_coverage, 0) + ' %' : '—'}</b><span>photos test au-dessus du seuil (précision mesurée ${cal.test_precision != null ? fmt(100 * cal.test_precision, 1) + ' %' : '—'})</span></div></div>
      <p class="micro">Images : entraînement ${fmt(m.images.train)}, validation ${fmt(m.images.val)}, test ${fmt(m.images.test)} — photos iNaturalist/GBIF prises en Normandie, photos d’une même observation jamais dans deux jeux.</p>
      <h3>Par groupe (test)</h3><div class="scroll"><table class="data"><tr><th>Groupe</th><th>Images</th><th>Top-1</th><th>Top-5</th></tr>
      ${Object.entries(m.per_group).sort((a, b) => b[1].images - a[1].images).map(([g, v]) => `<tr><td>${esc(GROUP_FR[g] || g)}</td><td>${fmt(v.images)}</td><td>${fmt(100 * v.top1, 1)} %</td><td>${fmt(100 * v.top5, 1)} %</td></tr>`).join('')}</table></div>
      <h3>Espèces les plus difficiles</h3><div class="scroll"><table class="data"><tr><th>Espèce</th><th>Images test</th><th>Top-1</th></tr>
      ${m.worst_classes.slice(0, 15).map(w => `<tr><td><i>${esc(w.species)}</i></td><td>${w.images}</td><td>${fmt(100 * w.top1, 0)} %</td></tr>`).join('')}</table></div>
      <h3>Apprentissage</h3><div class="scroll"><table class="data"><tr><th>Époque</th><th>Perte</th><th>Val top-1</th><th>Val top-5</th></tr>
      ${m.history.map(h => `<tr><td>${h.epoch}</td><td>${fmt(h.train_loss, 3)}</td><td>${fmt(100 * h.val_top1, 1)} %</td><td>${fmt(100 * h.val_top5, 1)} %</td></tr>`).join('')}</table></div>`;
  } catch (e) { $('#modelinfo').innerHTML = `<div class="error">${esc(e.message)}</div>`; }
}
