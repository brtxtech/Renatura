import { $, esc, fmt, loadJSON, ramp } from './extensions-common.js';
import { attachOrientation } from './orientation.js';

const [buyer, prices] = await Promise.all([loadJSON('data/normandie/buyer_cells.json'), loadJSON('data/normandie/prices.json')]);
const cells = buyer.cells;
const DEPT = { 14: 'Calvados', 27: 'Eure', 50: 'Manche', 61: 'Orne', 76: 'Seine-Maritime' };
const priceOf = c => (c.price.agri || c.price.rural || {}).median;
const value = { price: priceOf, rp: c => c.rp, ratio: c => c.rp_per_10k_eur };
const ranges = {};
for (const k of Object.keys(value)) {
  const v = cells.map(value[k]).filter(Number.isFinite).sort((a, b) => a - b);
  ranges[k] = [v[Math.floor(v.length * 0.02)], v[Math.floor(v.length * 0.98)]];
}

const map = L.map('map', { preferCanvas: true }).setView([49.1, 0.0], 8);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18, attribution: '© OpenStreetMap' }).addTo(map);
const renderer = L.canvas({ padding: 0.3 });
// Landmarks: commune names (always) + optional roads / rail / stops (OSM), same control as the other maps.
attachOrientation(map, 'leaflet');
// The selected cell: orange ring + commune name, so the card on the right is easy to find on the map.
const highlight = L.layerGroup().addTo(map);
function markCell(c) {
  highlight.clearLayers();
  L.circleMarker([c.lat, c.lon], { radius: 9, color: '#c27028', weight: 3, fill: false, interactive: false }).addTo(highlight);
  L.tooltip({ permanent: true, direction: 'top', offset: [0, -10], className: 'cell-label', interactive: false })
    .setLatLng([c.lat, c.lon]).setContent(esc(c.commune || c.id)).addTo(highlight);
}
const markers = cells.map(c => L.circleMarker([c.lat, c.lon], { renderer, radius: 3, weight: 0, fillOpacity: 0.85 })
  .on('click', () => showCard(c)).addTo(map));

function colour() {
  const k = $('#metric').value, [lo, hi] = ranges[k];
  const stops = k === 'price' ? ['#fff5eb', '#fdd0a2', '#fd8d3c', '#d94801', '#7f2704'] : undefined;
  markers.forEach((m, i) => m.setStyle({ fillColor: ramp((value[k](cells[i]) - lo) / (hi - lo), stops) }));
  const unit = { price: '€/ha', rp: 'points', ratio: 'RP / 10 k€' }[k];
  $('#legend').innerHTML = `<span>${fmt(lo, k === 'ratio' ? 1 : 0)}</span>${[0, .25, .5, .75, 1].map(t => `<i style="background:${ramp(t, stops)}"></i>`).join('')}<span>${fmt(hi, k === 'ratio' ? 1 : 0)} ${unit}</span><span>· gris = pas de donnée</span>`;
}
$('#metric').addEventListener('change', colour);
colour();

function priceBlock(label, p) {
  if (!p) return `<tr><td>${label}</td><td colspan="3" class="muted">pas assez de ventes (&lt; 5)</td></tr>`;
  return `<tr><td>${label}</td><td><b>${fmt(p.median)} €/ha</b></td><td>${fmt(p.p25)} – ${fmt(p.p75)}</td><td>${p.n} ventes · ${esc(p.level)}</td></tr>`;
}

function showCard(c) {
  markCell(c);
  const ref = prices.meta.bareme_by_department[c.department];
  const area = c.area_ha, med = priceOf(c);
  $('#cardbox').innerHTML = `<div class="eyebrow">Fiche acquéreur · ${esc(c.id)}</div>
    <h2>${esc(c.commune || 'Maille régionale')} <span class="muted">${esc(DEPT[c.department] || '')}</span></h2>
    <div class="kpis">
      <div class="kpi"><b>${fmt(med)} €</b><span>par ha (médiane agricole)</span></div>
      <div class="kpi"><b>${fmt(med * area / 1000)} k€</b><span>ordre de grandeur pour ${fmt(area, 0)} ha</span></div>
      <div class="kpi"><b>${fmt(c.rp, 0)}</b><span>priorité de restauration /100</span></div>
      <div class="kpi"><b>${fmt(c.rp_per_10k_eur, 1)}</b><span>points RP par 10 000 €/ha</span></div></div>
    <h3>Prix</h3><div class="scroll"><table class="data"><tr><th></th><th>Médiane</th><th>25–75 %</th><th>Base</th></tr>
      ${priceBlock('Terres et prés', c.price.agri)}${priceBlock('Bois', c.price.forest)}${priceBlock('Tout rural', c.price.rural)}</table></div>
    ${ref ? `<p class="micro">Référence officielle 2024 (${esc(DEPT[c.department])}, terres et prairies) : dominante médiane des petites régions ${fmt(ref.dominant_median_of_regions)} €/ha, fourchette ${fmt(ref.min)} – ${fmt(ref.max)} €/ha.</p>` : ''}
    <h3>Bénéfice écologique</h3>
    <table class="data"><tr><td>V · valeur écologique</td><td>${bar(c.V)}</td></tr><tr><td>D · dégradation à réparer</td><td>${bar(c.D)}</td></tr>
      <tr><td>P · pression humaine</td><td>${bar(c.P)}</td></tr><tr><td>O · opportunité d’action</td><td>${bar(c.O)}</td></tr></table>
    <p>${c.corridor ? '<span class="chip ok">Sur un corridor écologique calculé</span>' : ''}
      ${c.designations.map(d => `<span class="chip">${esc(d)}</span>`).join('') || '<span class="micro">Aucune désignation sur la maille.</span>'}</p>
    <p class="micro">Contraintes et aides à vérifier : zonage du PLU (A/N/U), Natura 2000 / ZNIEFF ci-dessus, droit de préemption SAFER, obligations réelles environnementales (ORE),
      paiements pour services environnementaux, Label bas-carbone (haies, boisement). Le potentiel carbone chiffré est une étape suivante.</p>`;
}
const bar = v => Number.isFinite(v) ? `<div class="bar"><i style="width:${v}%"></i></div>${fmt(v, 0)}` : '—';

function ranking() {
  const max = +$('#maxprice').value, min = +$('#minrp').value;
  const rows = cells.filter(c => Number.isFinite(c.rp_per_10k_eur) && priceOf(c) <= max && c.rp >= min)
    .sort((a, b) => b.rp_per_10k_eur - a.rp_per_10k_eur).slice(0, 15);
  $('#ranking').innerHTML = rows.length ? `<table class="data"><tr><th>Maille</th><th>€/ha</th><th>RP</th><th>RP/10k€</th></tr>${rows.map(c => `
    <tr data-id="${esc(c.id)}" style="cursor:pointer"><td>${esc(c.commune || c.id)}</td><td>${fmt(priceOf(c))}</td><td>${fmt(c.rp, 0)}</td><td>${fmt(c.rp_per_10k_eur, 1)}</td></tr>`).join('')}</table>`
    : '<p class="muted">Aucune maille ne correspond.</p>';
  document.querySelectorAll('#ranking tr[data-id]').forEach(tr => tr.addEventListener('click', () => {
    const c = cells.find(x => x.id === tr.dataset.id); showCard(c); map.setView([c.lat, c.lon], 12);
  }));
}
['#maxprice', '#minrp'].forEach(s => $(s).addEventListener('input', ranking));
ranking();

$('#search').addEventListener('change', e => {
  const q = e.target.value.trim().toLowerCase();
  const hit = cells.find(c => (c.commune || '').toLowerCase().startsWith(q));
  if (hit) { map.setView([hit.lat, hit.lon], 12); showCard(hit); }
});

const m = prices.meta;
$('#method').innerHTML = `<h3>Méthode et limites</h3><ul>${[...m.rules, buyer.meta.note].map(r => `<li>${esc(r)}</li>`).join('')}</ul>
  <p class="micro">Sources : ${m.sources.map(esc).join(' · ')}. ${fmt(m.rural_sales)} ventes rurales retenues
  (agricoles ${fmt(m.sales_by_category.agri)}, bois ${fmt(m.sales_by_category.forest || 0)}). Niveaux utilisés : ${Object.entries(m.levels_used).map(([k, v]) => `${esc(k)} ${fmt(v)}`).join(' · ')}.</p>
  <h3>Contrôle : DVF vs barème officiel 2024 (terres et prairies, €/ha)</h3><table class="data"><tr><th>Département</th><th>Médiane DVF</th><th>Barème (médiane des petites régions)</th></tr>
  ${Object.entries(DEPT).map(([d, n]) => `<tr><td>${n}</td><td>${fmt(m.department_dvf[`${d}|agri`]?.median)}</td><td>${fmt(m.bareme_by_department[d]?.dominant_median_of_regions)}</td></tr>`).join('')}</table>
  <p class="micro">Accès : cette version locale n’applique pas de contrôle d’accès ; une mise en ligne devra réserver la fiche aux utilisateurs connectés (conditions DVF).</p>`;
