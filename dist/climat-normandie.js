import { $, esc, fmt, loadJSON, ramp, lineChart, DIVERGING } from './extensions-common.js';

let data;
try { data = await loadJSON('data/normandie/climate.json'); }
catch (e) {
  const s = $('#status'); s.hidden = false;
  s.innerHTML = 'Données climatiques pas encore construites : <code>.venv-normandie/bin/python tools/normandie/climate_history.py build</code>';
  throw e;
}
const points = data.points;
const LABEL = { tmean: ['Température moyenne', '°C'], hot_days: ['Jours ≥ 30 °C', 'jours'], rain_mm: ['Pluie annuelle', 'mm'],
  max_dry_spell: ['Plus longue période sèche', 'jours'], dry_days: ['Jours secs (< 1 mm)', 'jours'], summer_rain_mm: ['Pluie d’été (JJA)', 'mm'],
  ndvi_summer: ['NDVI d’été (verdure)', ''] };

const map = L.map('map', { preferCanvas: true }).setView([49.1, 0.0], 8);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18, attribution: '© OpenStreetMap' }).addTo(map);
const renderer = L.canvas({ padding: 0.3 });
const pointLayer = L.layerGroup().addTo(map);
let cellLayer = null;

function draw() {
  const k = $('#layer').value;
  pointLayer.clearLayers();
  if (cellLayer) { map.removeLayer(cellLayer); cellLayer = null; }
  if (k === 'built') return drawBuilt();
  const vals = points.map(p => p.trends[k]?.slope_per_decade).filter(Number.isFinite);
  const m = Math.max(...vals.map(Math.abs), 1e-9);
  points.forEach(p => {
    const t = p.trends[k];
    const v = t?.slope_per_decade;
    L.circleMarker([p.lat, p.lon], { radius: 16, weight: t?.significant ? 2.5 : 0.5, color: '#173d31',
      fillColor: ramp((v / m + 1) / 2, k === 'rain_mm' || k === 'ndvi_summer' ? [...DIVERGING].reverse() : DIVERGING), fillOpacity: 0.85 })
      .bindTooltip(`${fmt(v, 3)} / décennie${t?.significant ? ' (significatif)' : ''}`)
      .on('click', () => detail(p)).addTo(pointLayer);
  });
  $('#legend').innerHTML = `<span>${fmt(-m, 2)}</span>${[0, .25, .5, .75, 1].map(t => `<i style="background:${ramp(t, k === 'rain_mm' || k === 'ndvi_summer' ? [...DIVERGING].reverse() : DIVERGING)}"></i>`).join('')}<span>+${fmt(m, 2)} / décennie · contour épais = tendance significative (p < 0,05)</span>`;
}

function drawBuilt() {
  const cells = data.cells;
  const ids = Object.keys(cells);
  // cells carry only attributes here: place them at their grid point offset is not possible, so use the explorer centroids
  loadJSON('data/normandie/buyer_cells.json').then(b => {
    const pos = Object.fromEntries(b.cells.map(c => [c.id, [c.lat, c.lon]]));
    cellLayer = L.layerGroup(ids.filter(id => pos[id] && cells[id].built_change_2006_2017_pts != null).map(id => {
      const v = cells[id].built_change_2006_2017_pts;
      return L.circleMarker(pos[id], { renderer, radius: 3, weight: 0, fillOpacity: 0.85, fillColor: ramp(Math.min(1, Math.max(0, v / 5)), ['#ffffe5', '#fee391', '#fe9929', '#cc4c02', '#662506']) })
        .on('click', () => cellDetail(id, cells[id]));
    })).addTo(map);
  });
  $('#legend').innerHTML = `<span>0</span>${[0, .25, .5, .75, 1].map(t => `<i style="background:${ramp(t, ['#ffffe5', '#fee391', '#fe9929', '#cc4c02', '#662506'])}"></i>`).join('')}<span>≥ +5 points de % de surface bâtie (2006 → 2017) · Eure et Seine-Maritime non mesurées (édition 2006 absente)</span>`;
}

function cellDetail(id, c) {
  $('#detail').innerHTML = `<div class="eyebrow">Maille ${esc(id)}</div><h2>Artificialisation</h2>
    <div class="kpis"><div class="kpi"><b>${c.built_2006 == null ? '—' : fmt(100 * c.built_2006, 1) + ' %'}</b><span>bâti 2006</span></div><div class="kpi"><b>${fmt(100 * c.built_2017, 1)} %</b><span>bâti 2017</span></div>
    <div class="kpi"><b>${c.built_change_2006_2017_pts == null ? '—' : (c.built_change_2006_2017_pts > 0 ? '+' : '') + fmt(c.built_change_2006_2017_pts, 2)}</b><span>évolution 2006 → 2017 (points de %)</span></div>
    <div class="kpi"><b>${fmt(100 * c.built_2025, 1)} %</b><span>bâti 2025 (niveau actuel, méthode différente : non comparable)</span></div></div>
    <p class="micro">Point climatique le plus proche : ${esc(c.point)}.</p>`;
  const p = points.find(x => x.id === c.point);
  if (p) $('#detail').insertAdjacentHTML('beforeend', '<hr>' + pointHTML(p));
}

function series(p, k) {
  const src = k.startsWith('ndvi') ? p.ndvi : p.climate;
  return Object.entries(src).map(([y, v]) => [+y, v[k]]).filter(([, v]) => Number.isFinite(v));
}
function baseline(pts) { const b = pts.filter(([y]) => y >= 1991 && y <= 2020).map(p => p[1]); return b.length ? b.reduce((a, c) => a + c, 0) / b.length : null; }
function pointHTML(p) {
  const blocks = ['tmean', 'hot_days', 'rain_mm', 'max_dry_spell', 'summer_rain_mm', 'ndvi_summer'].map(k => {
    const s = series(p, k); if (!s.length) return '';
    const t = p.trends[k], an = p.anomaly_2016_2025_vs_1991_2020?.[k];
    return `<h3>${LABEL[k][0]} ${LABEL[k][1] ? `(${LABEL[k][1]})` : ''}</h3>
      ${lineChart([{ points: s, color: '#2f7d5b' }], { yLabel: LABEL[k][0], baseline: baseline(s) })}
      <p class="micro">Tendance ${t ? `${fmt(t.slope_per_decade, 3)} / décennie, p = ${fmt(t.p_value, 3)} ${t.significant ? '<span class="chip warn">significative</span>' : '<span class="chip">non significative</span>'}` : '—'}
      ${an != null ? ` · 2016–2025 vs 1991–2020 : ${an > 0 ? '+' : ''}${fmt(an, 2)}` : ''} · pointillés = moyenne 1991–2020</p>`;
  }).join('');
  return `<div class="eyebrow">Point de grille ${esc(p.id)}</div><h2>${fmt(p.lat, 2)}° N, ${fmt(p.lon, 2)}° E</h2>${blocks}`;
}
function detail(p) { $('#detail').innerHTML = pointHTML(p); }

$('#layer').addEventListener('change', draw);
draw();
const m = data.meta;
$('#method').innerHTML = `<h3>Méthode</h3><ul><li>Référence ${esc(m.baseline)} ; période récente ${esc(m.recent_period)}.</li><li>${esc(m.trend_method)}.</li></ul>
  <p class="micro">Sources : ${m.sources.map(esc).join(' · ')}</p>`;
