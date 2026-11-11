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
  if (!(c.V >= 10)) return null;  // same eligibility rule as the explorer
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
  return { members, cells };
}

function analyse(fit = false) {
  const { members, cells } = selection();
  if (!cells.length) return status('Aucune maille régionale dans cette commune.');
  const s = state.size * 1000, groups = new Map();
  for (const i of cells) {
    const key = `${Math.floor(pts.x[i] / s)}_${Math.floor(pts.y[i] / s)}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(i);
  }
  const inCommune = new Set(members);
  state.squares = [...groups.entries()].map(([key, idx]) => {
    const [gx, gy] = key.split('_').map(Number);
    const area = idx.reduce((t, i) => t + (pts.area[i] || 0), 0);
    const sq = { key, gx, gy, cells: idx.length, area, inCommune: idx.filter(i => inCommune.has(i)).length,
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
      .bindTooltip(`${metric} ${fmt(sq[metric], 0)} · ${sq.cells} maille(s) 1 km²`)
      .on('click', () => { state.selected = sq.key; showSquare(sq); draw(); })
      .addTo(grid);
  }
  summary();
}

function summary() {
  const metric = $('#metric').value, name = pts.communes[state.commune].name, sq = state.squares;
  const allCells = sq.reduce((t, x) => t + x.cells, 0), area = sq.reduce((t, x) => t + x.area, 0);
  const zoneMean = k => mean(sq.map(x => x[k]), sq.map(x => x.area));
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

function showSquare(sq) {
  const box = $('#square');
  box.hidden = false;
  box.innerHTML = `<div class="eyebrow">Maille ${state.size} × ${state.size} km · ${sq.gx * state.size}_${sq.gy * state.size} km (Lambert-93)</div>
    <h3>${esc(sq.communes.slice(0, 4).join(', ') || 'Hors commune')}</h3>
    <table class="data">${[['RP', 'Priorité de restauration'], ['V', 'Valeur écologique'], ['D', 'Dégradation'], ['P', 'Pression humaine'], ['O', 'Opportunité d’action']]
      .map(([k, l]) => `<tr><td><b>${k}</b> · ${l}</td><td style="width:45%"><div class="bar"><i style="width:${sq[k] ?? 0}%;background:${colour(sq[k])}"></i></div></td><td>${fmt(sq[k], 1)}</td></tr>`).join('')}</table>
    <p class="micro">${sq.cells} maille(s) régionale(s) de 1 km² · ${fmt(sq.area, 0)} ha · dont ${sq.inCommune} dans ${esc(pts.communes[state.commune].name)}.
      Ouvrir l’<a href="explorer-normandie.html">explorateur Normandie</a> pour le détail des sources d’une maille de 1 km².</p>`;
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
