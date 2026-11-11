import { $, esc, fmt, loadJSON } from './extensions-common.js';

// ---------- Lambert-93 (EPSG:2154) -> WGS84, analytic inverse (GRS80); checked against pyproj (< 2 m)
const A = 6378137, E = 0.0818191910428158, RAD = Math.PI / 180;
const LON0 = 3 * RAD, PHI0 = 46.5 * RAD, PHI1 = 44 * RAD, PHI2 = 49 * RAD, X0 = 700000, Y0 = 6600000;
const mf = p => Math.cos(p) / Math.sqrt(1 - (E * Math.sin(p)) ** 2);
const tf = p => Math.tan(Math.PI / 4 - p / 2) / ((1 - E * Math.sin(p)) / (1 + E * Math.sin(p))) ** (E / 2);
const N = Math.log(mf(PHI1) / mf(PHI2)) / Math.log(tf(PHI1) / tf(PHI2));
const F = mf(PHI1) / (N * tf(PHI1) ** N), RHO0 = A * F * tf(PHI0) ** N;
function toLatLng(x, y) {
  const dx = x - X0, dy = RHO0 - (y - Y0);
  const t = (Math.sign(N) * Math.hypot(dx, dy) / (A * F)) ** (1 / N);
  let phi = Math.PI / 2 - 2 * Math.atan(t);
  for (let i = 0; i < 8; i++) phi = Math.PI / 2 - 2 * Math.atan(t * ((1 - E * Math.sin(phi)) / (1 + E * Math.sin(phi))) ** (E / 2));
  return [phi / RAD, (Math.atan2(dx, dy) / N + LON0) / RAD];
}

// ---------- state
const KEYS = ['V', 'D', 'P', 'O'];
const PALETTE = ['#e6e9b4', '#a5c784', '#659d70', '#326f59', '#164538'];
const state = { size: 1, weights: [0.30, 0.30, 0.15, 0.25], commune: null, squares: [], selected: null };
const status = m => { const s = $('#status'); s.hidden = !m; s.textContent = m || ''; };

status('Chargement des données…');
const [pts, communes] = await Promise.all([loadJSON('data/normandie/cells_points.json'), loadJSON('data/normandie/communes.geojson')]);
status('');
const byName = new Map(pts.communes.map((c, i) => [c.name.toLowerCase(), i]));
$('#communes').innerHTML = pts.communes.map(c => `<option value="${esc(c.name)}">${esc(c.insee)}</option>`).join('');
const HEX_R = 650;  // circumradius of a 1 km² hexagon ≈ 620 m (+ margin)
const buckets = new Map();
pts.id.forEach((_, i) => {
  const k = `${Math.floor(pts.x[i] / 1000)}_${Math.floor(pts.y[i] / 1000)}`;
  if (!buckets.has(k)) buckets.set(k, []);
  buckets.get(k).push(i);
});
function nearestCell(x, y) {
  let best = -1, dist = HEX_R;
  const bx = Math.floor(x / 1000), by = Math.floor(y / 1000);
  for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
    for (const i of buckets.get(`${bx + dx}_${by + dy}`) || []) {
      const d = Math.hypot(pts.x[i] - x, pts.y[i] - y);
      if (d < dist) { dist = d; best = i; }
    }
  }
  return best;
}
const regional = Object.fromEntries(KEYS.map(k => [k, mean(pts[k], pts.area)]));

const map = L.map('map', { preferCanvas: true }).setView([49.1, 0.0], 8);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18, attribution: '© OpenStreetMap' }).addTo(map);
const outline = L.layerGroup().addTo(map), grid = L.layerGroup().addTo(map);

// ---------- weights
$('#weights').innerHTML = KEYS.map((k, i) => `<label>${k} <b id="w${i}">${Math.round(state.weights[i] * 100)}</b> %<input type="range" min="0" max="100" value="${state.weights[i] * 100}" data-w="${i}"></label>`).join('');
document.querySelectorAll('[data-w]').forEach(r => r.addEventListener('input', () => {
  state.weights[+r.dataset.w] = +r.value / 100;
  $(`#w${r.dataset.w}`).textContent = r.value;
  if (state.commune != null) analyse();
}));

// ---------- controls
$('#commune').addEventListener('change', () => {
  const i = byName.get($('#commune').value.trim().toLowerCase());
  if (i == null) return status('Commune introuvable : choisir un nom dans la liste.');
  status(''); state.commune = i; analyse(true);
});
$('#zone').addEventListener('change', () => state.commune != null && analyse(true));
$('#metric').addEventListener('change', () => state.commune != null && draw());
document.querySelectorAll('[data-size]').forEach(b => b.addEventListener('click', () => {
  state.size = +b.dataset.size;
  document.querySelectorAll('[data-size]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
  if (state.commune != null) analyse();
}));

function mean(values, weights) {
  let s = 0, w = 0;
  values.forEach((v, i) => { if (v != null) { s += v * weights[i]; w += weights[i]; } });
  return w ? s / w : null;
}
function rp(c) {
  // Same rule as the regional explorer: every square with data gets a score (low V is flagged, not hidden).
  let s = 0, w = 0;
  KEYS.forEach((k, i) => { if (c[k] != null) { s += c[k] * state.weights[i]; w += state.weights[i]; } });
  return w ? s / w : null;
}

// ---------- analysis
function selection() {
  const ci = state.commune, members = [];
  pts.commune.forEach((c, i) => { if (c === ci) members.push(i); });
  if (!members.length) return { members, cells: [] };
  const pad = +$('#zone').value * 1000;
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  members.forEach(i => { x0 = Math.min(x0, pts.x[i]); x1 = Math.max(x1, pts.x[i]); y0 = Math.min(y0, pts.y[i]); y1 = Math.max(y1, pts.y[i]); });
  x0 -= pad + 600; y0 -= pad + 600; x1 += pad + 600; y1 += pad + 600;  // +600 m: half a cell around the extreme centres
  const cells = pad === 0 ? members : pts.id.map((_, i) => i).filter(i => pts.x[i] >= x0 && pts.x[i] <= x1 && pts.y[i] >= y0 && pts.y[i] <= y1);
  return { members, cells, pad, box: [x0, y0, x1, y1] };
}

function analyse(fit = false) {
  const { members, cells, pad, box } = selection();
  if (!cells.length) return status('Aucune maille régionale dans cette commune.');
  const s = state.size * 1000, groups = new Map();
  for (const i of cells) {
    const key = `${Math.floor(pts.x[i] / s)}_${Math.floor(pts.y[i] / s)}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(i);
  }
  // A 1 km square can fall between hexagon centres (spacing ≈ 1.07 km) and would stay empty although it is
  // covered: give it the 1 km² cell whose hexagon contains its centre. Squares over the sea / outside Normandy stay empty.
  const filled = new Set();
  const keys = [...groups.keys()].map(k => k.split('_').map(Number));
  if (keys.length) {
    const gx0 = Math.min(...keys.map(k => k[0])), gx1 = Math.max(...keys.map(k => k[0]));
    const gy0 = Math.min(...keys.map(k => k[1])), gy1 = Math.max(...keys.map(k => k[1]));
    for (let gx = gx0; gx <= gx1; gx++) for (let gy = gy0; gy <= gy1; gy++) {
      const key = `${gx}_${gy}`;
      if (groups.has(key)) continue;
      const cx = (gx + 0.5) * s, cy = (gy + 0.5) * s;
      if (pad > 0 && (cx < box[0] || cx > box[2] || cy < box[1] || cy > box[3])) continue;
      const i = nearestCell(cx, cy);
      if (i < 0 || (pad === 0 && pts.commune[i] !== state.commune)) continue;
      groups.set(key, [i]);
      filled.add(key);
    }
  }
  const inCommune = new Set(members);
  state.squares = [...groups.entries()].map(([key, idx]) => {
    const [gx, gy] = key.split('_').map(Number);
    const area = idx.reduce((t, i) => t + (pts.area[i] || 0), 0);
    const sq = { key, gx, gy, idx, cells: idx.length, area, filled: filled.has(key), inCommune: idx.filter(i => inCommune.has(i)).length,
      communes: [...new Set(idx.map(i => pts.commune[i]).filter(c => c >= 0))].map(c => pts.communes[c].name) };
    for (const k of KEYS) sq[k] = mean(idx.map(i => pts[k][i]), idx.map(i => pts.area[i] || 0));
    sq.RP = rp(sq);
    return sq;
  });
  state.selected = null;
  $('#square').hidden = true;
  drawOutline(fit);
  draw();
}

function drawOutline(fit) {
  outline.clearLayers();
  const f = communes.features[state.commune];
  if (!f) return;
  const layer = L.geoJSON(f, { style: { color: '#c27028', weight: 3, fill: false, dashArray: '6 4' }, interactive: false }).addTo(outline);
  if (fit) map.fitBounds(layer.getBounds().pad(+$('#zone').value > 0 ? 0.6 : 0.15));
}

const colour = v => v == null ? '#c7cdc3' : PALETTE[Math.min(4, Math.floor(v / 20))];

function draw() {
  const metric = $('#metric').value, s = state.size * 1000;
  grid.clearLayers();
  for (const sq of state.squares) {
    const x = sq.gx * s, y = sq.gy * s;
    const ring = [[x, y], [x + s, y], [x + s, y + s], [x, y + s]].map(([a, b]) => toLatLng(a, b));
    L.polygon(ring, { color: sq.key === state.selected ? '#c27028' : '#fafbee', weight: sq.key === state.selected ? 3 : 0.8,
      fillColor: colour(sq[metric]), fillOpacity: 0.8 })
      .bindTooltip(`${metric} ${fmt(sq[metric], 0)} · ${sq.filled ? 'valeur de la maille 1 km² qui couvre ce carré' : `${sq.cells} maille(s) 1 km²`}${sq.V < 10 ? ' · V faible' : ''}`)
      .on('click', () => { state.selected = sq.key; showSquare(sq); draw(); })
      .addTo(grid);
  }
  summary();
}

function summary() {
  const metric = $('#metric').value, name = pts.communes[state.commune].name, sq = state.squares;
  const own = sq.filter(x => !x.filled);  // filled squares reuse a neighbour cell: not counted twice
  const allCells = own.reduce((t, x) => t + x.cells, 0), area = own.reduce((t, x) => t + x.area, 0);
  const zoneMean = k => mean(own.map(x => x[k]), own.map(x => x.area));
  const vals = sq.map(x => x[metric]).filter(v => v != null);
  const bins = Array(10).fill(0);
  vals.forEach(v => bins[Math.min(9, Math.floor(v / 10))]++);
  const top = Math.max(1, ...bins);
  const rpRegional = rp(regional);
  $('#summary').innerHTML = `<div class="eyebrow">${esc(name)} · ${esc($('#zone').selectedOptions[0].text)} · mailles ${state.size} × ${state.size} km</div>
    <div class="kpis"><div class="kpi"><b>${fmt(sq.length)}</b><span>mailles de ${state.size} km</span></div>
      <div class="kpi"><b>${fmt(allCells)}</b><span>mailles régionales de 1 km²</span></div>
      <div class="kpi"><b>${fmt(area / 100, 0)} km²</b><span>surface analysée</span></div>
      <div class="kpi"><b>${fmt(zoneMean(metric === 'RP' ? 'RP' : metric), 0)}</b><span>${esc(metric)} moyen de la zone</span></div></div>
    <table class="data cmp"><tr><th>Critère</th><th>Zone</th><th>Normandie</th></tr>
      ${[['RP', 'Priorité de restauration', zoneMean('RP'), rpRegional], ...KEYS.map((k, i) => [k, ['Valeur écologique', 'Dégradation', 'Pression humaine', 'Opportunité d’action'][i], zoneMean(k), regional[k]])]
        .map(([k, label, z, r]) => `<tr><td><b>${k}</b> · ${label}</td><td>${fmt(z, 1)}</td><td>${fmt(r, 1)}</td></tr>`).join('')}</table>
    <h3 style="margin-top:14px">Répartition de ${esc(metric)} (${vals.length} mailles)</h3>
    <div class="hist">${bins.map((n, i) => `<div style="height:${(100 * n / top).toFixed(0)}%;background:${colour(i * 10 + 5)}" title="${i * 10}–${i * 10 + 10} : ${n}"><span>${i * 10}</span></div>`).join('')}</div>
    <p style="margin-top:22px"><button class="secondary" id="csv">Exporter les mailles (CSV)</button></p>`;
  $('#csv').addEventListener('click', exportCSV);
  table();
}

function table() {
  const metric = $('#metric').value;
  const rows = [...state.squares].filter(s => s[metric] != null).sort((a, b) => b[metric] - a[metric]).slice(0, 12);
  const t = $('#table');
  t.hidden = false;
  t.innerHTML = `<h3>Mailles les plus élevées · ${esc(metric)}</h3><div class="scroll"><table class="data"><tr><th>Maille (Lambert-93)</th><th>Communes</th><th>RP</th><th>V</th><th>D</th><th>P</th><th>O</th><th>Mailles 1 km²</th></tr>
    ${rows.map(s => `<tr data-key="${s.key}" style="cursor:pointer"><td>${s.gx * state.size}_${s.gy * state.size} km</td><td>${esc(s.communes.slice(0, 3).join(', '))}${s.communes.length > 3 ? '…' : ''}</td>
      ${['RP', ...KEYS].map(k => `<td>${fmt(s[k], 0)}</td>`).join('')}<td>${s.cells}</td></tr>`).join('')}</table></div>`;
  t.querySelectorAll('tr[data-key]').forEach(tr => tr.addEventListener('click', () => {
    const sq = state.squares.find(s => s.key === tr.dataset.key);
    state.selected = sq.key; showSquare(sq); draw();
    const s = state.size * 1000;
    map.setView(toLatLng((sq.gx + 0.5) * s, (sq.gy + 0.5) * s), Math.max(map.getZoom(), 11));
  }));
}

// ---------- why: per-criterion evidence stored for every 1 km² cell (tools/normandie/build_display.py -> cells_detail/<col>.json)
const detailChunks = new Map();
async function cellDetails(ids) {
  const cols = [...new Set(ids.map(id => String(id).split('_')[1]))];
  await Promise.all(cols.map(c => {
    if (!detailChunks.has(c)) detailChunks.set(c, loadJSON(`data/normandie/cells_detail/${c}.json`).catch(() => ({})));
    return detailChunks.get(c);
  }));
  const out = [];
  for (const id of ids) out.push((await detailChunks.get(String(id).split('_')[1]))[id] || null);
  return out;
}
const CRIT = {
  V: { label: 'Valeur écologique', high: 'beaucoup de structure naturelle', low: 'peu de structure naturelle' },
  D: { label: 'Dégradation', high: 'milieu nettement dégradé', low: 'peu de dégradation mesurée' },
  P: { label: 'Pression humaine', high: 'forte présence humaine', low: 'faible présence humaine' },
  O: { label: 'Opportunité d’action', high: 'nombreux leviers d’action documentés', low: 'peu de leviers d’action documentés' },
};
const level = v => v == null ? 'inconnu' : v >= 66 ? 'élevé' : v >= 33 ? 'moyen' : 'faible';
function measure(value, unit) {
  if (value == null) return '—';
  if (/^Δ/.test(unit || '')) return `${value >= 0 ? '+' : ''}${fmt(value * 100, 1)} points de surface bâtie`;
  if (/part/.test(unit || '')) return `${fmt(value * 100, value < 0.1 ? 1 : 0)} % de la maille`;
  return `${fmt(value, value < 10 ? 1 : 0)} ${unit || ''}`.trim();
}
// Area-weighted merge of the evidence of the cells that make up a square.
function mergeEvidence(details, weights, k) {
  const rows = new Map();
  details.forEach((d, j) => (d?.evidence?.[k] || []).forEach(e => {
    const r = rows.get(e.metric) || { metric: e.metric, unit: e.unit, year: e.year, v: 0, s: 0, w: 0 };
    r.v += (e.value ?? 0) * weights[j]; r.s += (e.score ?? 0) * weights[j]; r.w += weights[j];
    rows.set(e.metric, r);
  }));
  const total = weights.reduce((a, b) => a + b, 0) || 1;
  return [...rows.values()].map(r => ({ ...r, value: r.v / total, score: r.s / total, share: r.w / total }))
    .sort((a, b) => b.score - a.score);
}
async function explainSquare(sq) {
  const box = $('#why');
  if (!box) return;
  const ids = sq.idx.map(i => pts.id[i]), weights = sq.idx.map(i => pts.area[i] || 0);
  const details = await cellDetails(ids);
  if (state.selected !== sq.key) return;  // another square was clicked meanwhile
  if (!details.some(Boolean)) { box.innerHTML = '<p class="micro">Détail des sources indisponible pour ce carré.</p>'; return; }
  const w = state.weights, wsum = KEYS.reduce((t, k, i) => t + (sq[k] != null ? w[i] : 0), 0) || 1;
  const parts = KEYS.filter(k => sq[k] != null).map(k => {
    const i = KEYS.indexOf(k);
    return `${k} ${fmt(sq[k], 0)} × ${Math.round(w[i] / wsum * 100)} % = ${fmt(sq[k] * w[i] / wsum, 1)}`;
  });
  const blocks = KEYS.map(k => {
    const ev = mergeEvidence(details, weights, k), c = CRIT[k], v = sq[k];
    const head = `<h4>${k} · ${c.label} : ${fmt(v, 0)} (${level(v)})</h4><p class="micro">${v == null ? 'Pas de donnée.' : v >= 66 ? c.high : v >= 33 ? 'niveau intermédiaire' : c.low} — ${ev.length ? 'principales couches :' : ''}</p>`;
    if (!ev.length) return head + `<p class="micro">Aucune couche de ce critère ne touche ce carré : la valeur reflète l’absence de signal (rang bas parmi les mailles normandes).</p>`;
    return head + `<ul class="why-list">${ev.slice(0, 4).map(e => `<li><b>${esc(e.metric)}</b>${e.year ? ` (${e.year})` : ''} : ${esc(measure(e.value, e.unit))}
      → plus que <b>${fmt(e.score, 0)} %</b> des mailles normandes${e.share < 0.99 ? ` <small>(sur ${fmt(e.share * 100, 0)} % du carré)</small>` : ''}</li>`).join('')}</ul>`;
  }).join('');
  box.innerHTML = `<h3 style="margin:14px 0 4px">Pourquoi ces valeurs ?</h3>
    <p class="micro">Chaque couche est mesurée dans la maille (part de surface, longueur ou nombre d’objets), puis comparée aux 30 850 mailles de Normandie : « plus que 92 % » veut dire que la maille dépasse 92 % des mailles normandes pour cette couche. Le critère combine ces rangs avec les pondérations de layer_scoring.json.</p>
    <p class="micro"><b>RP ${fmt(sq.RP, 1)}</b> = ${parts.join(' + ')}</p>${blocks}`;
}

function showSquare(sq) {
  const box = $('#square');
  box.hidden = false;
  box.innerHTML = `<div class="eyebrow">Maille ${state.size} × ${state.size} km · ${sq.gx * state.size}_${sq.gy * state.size} km (Lambert-93)</div>
    <h3>${esc(sq.communes.slice(0, 4).join(', ') || 'Hors commune')}</h3>
    <table class="data">${[['RP', 'Priorité de restauration'], ['V', 'Valeur écologique'], ['D', 'Dégradation'], ['P', 'Pression humaine'], ['O', 'Opportunité d’action']]
      .map(([k, l]) => `<tr><td><b>${k}</b> · ${l}</td><td style="width:45%"><div class="bar"><i style="width:${sq[k] ?? 0}%;background:${colour(sq[k])}"></i></div></td><td>${fmt(sq[k], 1)}</td></tr>`).join('')}</table>
    ${sq.V < 10 ? '<p class="micro"><b>Valeur écologique faible (V &lt; 10)</b> : peu de structure naturelle restante (zone bâtie ou très artificialisée).</p>' : ''}
    ${sq.filled ? '<p class="micro">Aucun centre de maille régionale ne tombe dans ce carré (les hexagones de 1 km² sont espacés d’environ 1,07 km) : valeurs de la maille de 1 km² qui couvre son centre.</p>' : ''}
    <p class="micro">${sq.cells} maille(s) régionale(s) de 1 km² · ${fmt(sq.area, 0)} ha · dont ${sq.inCommune} dans ${esc(pts.communes[state.commune].name)}.
      Ouvrir l’<a href="explorer-normandie.html">explorateur Normandie</a> pour le détail des sources d’une maille de 1 km².</p>
    <div id="why"><p class="micro">Chargement des explications…</p></div>`;
  explainSquare(sq);
}

function exportCSV() {
  const head = ['maille_l93_km', 'taille_km', 'communes', 'RP', ...KEYS, 'mailles_1km2', 'surface_ha'];
  const lines = state.squares.map(s => [`${s.gx * state.size}_${s.gy * state.size}`, state.size, `"${s.communes.join(' | ').replace(/"/g, '""')}"`,
    ...['RP', ...KEYS].map(k => s[k] == null ? '' : s[k].toFixed(2)), s.cells, s.area.toFixed(1)].join(','));
  const blob = new Blob([[head.join(','), ...lines].join('\n')], { type: 'text/csv;charset=utf-8' });
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: `renatura_${pts.communes[state.commune].name}_${state.size}km.csv` });
  a.click();
  URL.revokeObjectURL(a.href);
}

// deep link: ville-normandie.html?commune=Caen&taille=4
const q = new URLSearchParams(location.search);
if (q.get('taille') && [1, 2, 4, 8].includes(+q.get('taille'))) document.querySelector(`[data-size="${q.get('taille')}"]`).click();
if (q.get('commune')) { $('#commune').value = q.get('commune'); $('#commune').dispatchEvent(new Event('change')); }
