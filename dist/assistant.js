// Renatura · Assistant IA page: chat with the local model (pipeline/assistant/chat.py, /api/assistant/*).
import { $, esc, loadJSON } from './extensions-common.js';

const EXAMPLES = [
  'Pourquoi la pression humaine est-elle forte à Caen ?',
  'Explique la priorité de restauration de la maille H1_538_6422.',
  'Quelles sont les mailles prioritaires de Lisieux ?',
  'Trouve des mailles similaires à H1_538_6422.',
  'Comment est calculée la valeur écologique V ?',
  'Quelle relation entre la pression humaine et la valeur écologique autour de Caen ?',
  'Si la tendance continue, quelle part bâtie à Caen en 2040 ?',
];
const history = [];
let photo = null, busy = false;

// ---------- model status
async function health() {
  try {
    const h = await (await fetch('api/assistant/health', { cache: 'no-store' })).json();
    $('#model-dot').className = 'dot ' + (h.ok ? 'ok' : 'bad');
    $('#model-text').textContent = h.ok ? `${h.model} prêt` : h.detail;
    const models = h.available_models?.length ? h.available_models : [h.model];
    $('#model').innerHTML = models.map(m => `<option ${m === h.model ? 'selected' : ''}>${esc(m)}</option>`).join('');
  } catch {
    $('#model-dot').className = 'dot bad';
    $('#model-text').textContent = 'Service indisponible : ouvrir la page sur http://localhost:8090/assistant.html';
  }
}

// ---------- rendering
const linkCells = html => html.replace(/\bH1_\d+_\d+\b/g, id => `<a class="cell" href="explorer-normandie.html?q=${id}" target="_blank" rel="noopener" title="Ouvrir dans l’explorateur">${id}</a>`);
function add(role, html) {
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.innerHTML = html;
  $('#messages').append(div);
  $('#messages').scrollTop = $('#messages').scrollHeight;
  return div;
}
function photoBox(p) {
  if (!p) return '';
  if (p.erreur) return `<div class="photo-box">Photo : ${esc(p.erreur)}</div>`;
  const sp = typeof p.espece === 'object' ? p.espece : null;
  return `<div class="photo-box"><b>Analyse de la photo</b><br>
    GPS : ${typeof p.gps === 'object' ? `${p.gps.lat}, ${p.gps.lon} → maille ${linkCells(esc(p.cell_id))}` : esc(p.gps)}<br>
    Espèce (modèle Renatura) : ${sp ? `<i>${esc(sp.proposition)}</i> ${sp.nom_francais ? '· ' + esc(sp.nom_francais) : ''} — ${Math.round(sp.probabilite * 100)} %, ${esc(sp.statut)}` : esc(p.espece || '—')}</div>`;
}
function toolsBox(r) {
  const calls = (r.tools || []).filter(t => t.tool && !t.note);
  const notes = (r.tools || []).filter(t => t.note).map(t => `<div>Attention : ${esc(t.note)}</div>`).join('');
  const list = calls.map(t => `<details><summary>${t.auto ? '[auto] ' : ''}${esc(t.tool)}(${esc(Object.entries(t.args || {}).map(([k, v]) => `${k}=${v}`).join(', '))})</summary><pre>${esc(JSON.stringify(t.result, null, 1))}</pre></details>`).join('');
  const warn = r.unverified?.length ? `<div style="color:var(--bad)">Attention : nombres non retrouvés dans les données des outils : ${r.unverified.map(esc).join(', ')} — à vérifier, le modèle a pu se tromper.</div>` : '';
  return `<div class="meta">${warn}${calls.length ? `Outils appelés (${calls.length}, [auto] = appelé automatiquement par le serveur) — les chiffres viennent d’ici :` : 'Aucun outil appelé : réponse sans donnée chiffrée vérifiée.'} ${list}${notes}
    <div>${esc(r.model)} · ${r.seconds} s</div></div>`;
}

// ---------- send
async function send(text) {
  if (busy) return;
  text = text.trim();
  if (!text && !photo) return;
  busy = true; $('#send').disabled = true;
  const preview = photo ? `<img class="preview" src="${URL.createObjectURL(photo)}" alt="">` : '';
  add('user', esc(text || 'Que montre cette photo ?') + preview);
  const t0 = Date.now();
  const typing = add('typing', 'L’assistant réfléchit… 0 s');
  const timer = setInterval(() => { typing.textContent = `L’assistant réfléchit et interroge les données… ${Math.round((Date.now() - t0) / 1000)} s`; }, 1000);
  const body = new FormData();
  body.append('message', text);
  body.append('history', JSON.stringify(history));
  body.append('model', $('#model').value || '');
  body.append('page_context', JSON.stringify({ page: 'assistant', commune: $('#ctx-commune').value.trim() || undefined, cell_id: $('#ctx-cell').value.trim() || undefined }));
  if (photo) body.append('photo', photo);
  clearPhoto();
  $('#input').value = '';
  try {
    const res = await fetch('api/assistant/chat', { method: 'POST', body });
    const r = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(r.detail || `HTTP ${res.status}`);
    add('bot', linkCells(esc(r.answer || '(réponse vide)')) + photoBox(r.photo) + toolsBox(r));
    history.push({ role: 'user', content: text }, { role: 'assistant', content: r.answer || '' });
  } catch (e) {
    add('error', 'Erreur : ' + esc(e.message) + '<br><span class="micro">Vérifier que le serveur 8090 et Ollama tournent.</span>');
  } finally {
    clearInterval(timer); typing.remove();
    busy = false; $('#send').disabled = false; $('#input').focus();
  }
}

// ---------- photo
function clearPhoto() { photo = null; $('#photo').value = ''; $('#attached').hidden = true; $('#attached').innerHTML = ''; }
$('#attach').addEventListener('click', () => $('#photo').click());
$('#photo').addEventListener('change', () => {
  const f = $('#photo').files[0];
  if (!f) return;
  if (f.size > 15 * 1024 * 1024) { alert('Photo trop lourde (15 Mo maximum).'); return clearPhoto(); }
  photo = f;
  $('#attached').hidden = false;
  $('#attached').innerHTML = `Photo jointe : ${esc(f.name)} <button type="button" id="unattach">Retirer</button>`;
  $('#unattach').onclick = clearPhoto;
});

// ---------- wiring
$('#composer').addEventListener('submit', e => { e.preventDefault(); send($('#input').value); });
$('#input').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send($('#input').value); } });
$('#input').addEventListener('input', e => { e.target.style.height = 'auto'; e.target.style.height = Math.min(160, e.target.scrollHeight) + 'px'; });
$('#examples').innerHTML = EXAMPLES.map(q => `<button type="button">${esc(q)}</button>`).join('');
$('#examples').querySelectorAll('button').forEach(b => b.addEventListener('click', () => send(b.textContent)));
document.querySelectorAll('.models-help .ask').forEach(b => b.addEventListener('click', () => { $('#messages').scrollIntoView({ behavior: 'smooth', block: 'center' }); send(b.textContent); }));
$('#clear').addEventListener('click', () => { history.length = 0; $('#messages').innerHTML = ''; welcome(); });
function welcome() {
  add('bot', 'Bonjour ! Posez une question sur une commune, une maille (ex. H1_538_6422) ou un indice, ou joignez une photo de terrain avec le bouton Photo.\nLes réponses du modèle local peuvent prendre une à deux minutes sur cet ordinateur.');
}
welcome();
health();
loadJSON('data/normandie/cells_points.json').then(p => {
  $('#communes').innerHTML = p.communes.map(c => `<option value="${esc(c.name)}"></option>`).join('');
}).catch(() => {});
