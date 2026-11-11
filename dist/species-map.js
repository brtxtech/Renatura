/** Observations naturalistes géolocalisées : carte + fiche image. Statique, aucun tracker. */
import { attachOrientation } from './orientation.js';

const GROUPS = {
  oiseaux: { label: 'Oiseaux', color: '#2a78d6' },
  mammiferes: { label: 'Mammifères', color: '#008300' },
  poissons: { label: 'Poissons', color: '#e87ba4' },
  insectes: { label: 'Insectes', color: '#eda100' },
};

const $ = (s) => document.querySelector(s);
const e = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const state = { active: new Set(Object.keys(GROUPS)), entries: [] }; // entries: [{record, marker}]

function renderFilters(counts) {
  const el = $('#sp-filters');
  el.innerHTML = Object.entries(GROUPS).map(([key, g]) => `
    <button class="sp-filter active" data-group="${key}" style="color:${g.color}">
      <i style="background:${g.color}"></i>${e(g.label)} <span class="count">${counts[key] || 0}</span>
    </button>`).join('');
  el.querySelectorAll('[data-group]').forEach((button) => {
    button.addEventListener('click', () => {
      const key = button.dataset.group;
      if (state.active.has(key)) { state.active.delete(key); button.classList.remove('active'); }
      else { state.active.add(key); button.classList.add('active'); }
      applyFilter();
    });
  });
}

function applyFilter() {
  let visible = 0;
  for (const { record, marker } of state.entries) {
    const show = state.active.has(record.group);
    if (show) { marker.addTo(window.__spLayer); visible++; } else { marker.remove(); }
  }
  $('#sp-stat').textContent = `${visible.toLocaleString('fr-FR')} / ${state.entries.length.toLocaleString('fr-FR')} observations affichées`;
}

function showPanel(record) {
  const g = GROUPS[record.group] || { label: record.group, color: '#666' };
  $('#sp-panel').innerHTML = `
    <img src="data/species-images/${e(record.img)}" alt="${e(record.fr || record.sci)}" loading="lazy">
    <h3>${e(record.fr || record.sci)}</h3>
    <p class="sci">${e(record.sci)}</p>
    <div class="sp-badge-row">
      <span class="sp-badge" style="background:${g.color}22;color:${g.color}">${e(g.label)}</span>
      ${record.protected ? '<span class="sp-badge protected">Protégée en France</span>' : ''}
      ${record.redlist ? `<span class="sp-badge redlist">Liste rouge Normandie : ${e(record.redlist)}</span>` : ''}
    </div>
    <dl class="sp-dl">
      <dt>Observée le</dt><dd>${e(record.date || '—')}</dd>
      <dt>Source</dt><dd>${e(record.src)}</dd>
      <dt>Licence</dt><dd>${e(record.lic)}</dd>
      <dt>Attribution</dt><dd>${e(record.attr)}</dd>
      <dt>Coordonnées</dt><dd>${record.lat.toFixed(4)}, ${record.lon.toFixed(4)}</dd>
    </dl>
    ${record.url ? `<a class="outline" href="${e(record.url)}" target="_blank" rel="noopener noreferrer">Voir l’observation ↗</a>` : ''}`;
}

async function loadBoundary(map) {
  try {
    const response = await fetch('data/normandie/boundary.geojson');
    if (!response.ok) return;
    const geojson = await response.json();
    L.geoJSON(geojson, { style: { color: '#56774e', weight: 1.5, fillColor: '#e9eee4', fillOpacity: 1, dashArray: '4 3' } }).addTo(map);
  } catch { /* Boundary is decorative context only; map still works without it. */ }
}

async function init() {
  const response = await fetch('data/species-observations.json');
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const records = await response.json();

  const counts = {};
  for (const r of records) counts[r.group] = (counts[r.group] || 0) + 1;
  renderFilters(counts);
  $('#sp-stat').textContent = `${records.length.toLocaleString('fr-FR')} / ${records.length.toLocaleString('fr-FR')} observations affichées`;

  const map = L.map('sp-map', { preferCanvas: true, zoomSnap: 0.25, attributionControl: false });
  const bounds = L.latLngBounds(records.map((r) => [r.lat, r.lon]));
  map.fitBounds(bounds, { padding: [30, 30] });

  await loadBoundary(map);
  attachOrientation(map, 'leaflet');

  const layer = L.layerGroup().addTo(map);
  window.__spLayer = layer;

  state.entries = records.map((record) => {
    const g = GROUPS[record.group] || { color: '#666' };
    const marker = L.circleMarker([record.lat, record.lon], {
      radius: 5, color: '#fff', weight: 1, fillColor: g.color, fillOpacity: 0.85,
    });
    marker.on('click', () => showPanel(record));
    marker.bindTooltip(record.fr || record.sci, { direction: 'top', offset: [0, -4] });
    marker.addTo(layer);
    return { record, marker };
  });
}

init().catch((error) => {
  $('#sp-map').innerHTML = `<p style="padding:16px;color:#8f2e2e">Données indisponibles : ${e(error.message)}</p>`;
});
