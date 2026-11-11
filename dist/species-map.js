/** Observations naturalistes géolocalisées : carte + fiche image. Statique, aucun tracker. */
import { attachOrientation } from './orientation.js';

const GROUPS = {
  oiseaux: { label: 'Oiseaux', color: '#2a78d6' },
  mammiferes: { label: 'Mammifères', color: '#008300' },
  poissons: { label: 'Poissons', color: '#e87ba4' },
  insectes: { label: 'Insectes', color: '#eda100' },
  amphibiens: { label: 'Amphibiens', color: '#0aa3a3' },
  reptiles: { label: 'Reptiles', color: '#8c5a2b' },
  mollusques: { label: 'Mollusques', color: '#9b59b6' },
  crustaces: { label: 'Crustacés', color: '#d35400' },
  arachnides: { label: 'Arachnides', color: '#555555' },
  plantes_a_fleurs: { label: 'Plantes à fleurs', color: '#c2185b' },
  fougeres: { label: 'Fougères', color: '#2e7d32' },
  coniferes: { label: 'Conifères', color: '#1b5e20' },
  mousses: { label: 'Mousses', color: '#7cb342' },
};

const $ = (s) => document.querySelector(s);
const e = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const state = { active: new Set(Object.keys(GROUPS)), status: 'all', entries: [] }; // entries: [{record, marker}]

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

// conservation-status filter for the map (combined with the group filter)
const THREAT = new Set(['CR', 'EN', 'VU']);
const STATUS_TEST = {
  all: () => true,
  threatened: (r) => THREAT.has(r.redlist),
  nt: (r) => r.redlist === 'NT',
  protected: (r) => !!r.protected,
};
const isShown = (r) => state.active.has(r.group) && STATUS_TEST[state.status](r);

function renderStatusFilter(records) {
  const el = $('#sp-map-status');
  el.querySelectorAll('[data-status]').forEach((b) => {
    const n = records.filter(STATUS_TEST[b.dataset.status]).length;
    b.insertAdjacentHTML('beforeend', ` <span class="count">${n.toLocaleString('fr-FR')}</span>`);
    b.addEventListener('click', () => {
      state.status = b.dataset.status;
      el.querySelectorAll('[data-status]').forEach((x) => x.classList.toggle('active', x === b));
      applyFilter();
    });
  });
}

function applyFilter() {
  let visible = 0;
  for (const { record, marker } of state.entries) {
    const show = isShown(record);
    if (show) { marker.addTo(window.__spLayer); visible++; } else { marker.remove(); }
  }
  $('#sp-stat').textContent = `${visible.toLocaleString('fr-FR')} / ${state.entries.length.toLocaleString('fr-FR')} observations affichées`;
  if (state.map) renderZone();
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
      <dt>Coordonnées</dt><dd>${record.lat.toFixed(4)}, ${record.lon.toFixed(4)}${record.generalised ? ' (espèce sensible : position à ~10 km près)' : ''}</dd>
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
  renderStatusFilter(records);
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
  state.map = map;
  buildSpecies(records);
  renderThreatened();
  map.on('moveend', renderZone);
  renderZone();
}

// ---------- galleries below the map: threatened / protected species, and species of the visible zone
const RANK = { CR: 0, EN: 1, VU: 2, NT: 3 };
const STATUS_FR = { CR: 'En danger critique', EN: 'En danger', VU: 'Vulnérable', NT: 'Quasi menacée' };
state.species = new Map();
state.threatFilter = 'threatened';

function buildSpecies(records) {
  for (const r of records) {
    if (!state.species.has(r.sci)) state.species.set(r.sci, { sci: r.sci, fr: r.fr, group: r.group, protected: r.protected, redlist: r.redlist, records: [] });
    state.species.get(r.sci).records.push(r);
  }
  document.querySelectorAll('#sp-threat-filter [data-status]').forEach((b) => b.addEventListener('click', () => {
    state.threatFilter = b.dataset.status;
    document.querySelectorAll('#sp-threat-filter [data-status]').forEach((x) => x.classList.toggle('active', x === b));
    renderThreatened();
  }));
  const intro = document.getElementById('sp-intro');
  if (intro) intro.innerHTML = `${records.length.toLocaleString('fr-FR')} observations géolocalisées de ${state.species.size.toLocaleString('fr-FR')} espèces (iNaturalist / GBIF), prises en Normandie et reliées chacune à une photo réelle. Cliquez un point pour voir l’image, l’espèce et sa provenance. Les couleurs distinguent les groupes — elles n’indiquent ni abondance ni priorité de conservation. Sous la carte : les espèces menacées et protégées, puis les espèces de la zone affichée.`;
}

function badges(sp) {
  const g = GROUPS[sp.group] || { label: sp.group, color: '#666' };
  return `<div class="sp-badge-row"><span class="sp-badge" style="background:${g.color}22;color:${g.color}">${e(g.label)}</span>
    ${sp.redlist && RANK[sp.redlist] !== undefined ? `<span class="sp-badge ${sp.redlist.toLowerCase()}">LR Normandie ${e(sp.redlist)} · ${e(STATUS_FR[sp.redlist])}</span>` : ''}
    ${sp.protected ? '<span class="sp-badge protected">Protégée en France</span>' : ''}</div>`;
}

function card(sp, records, extra = '') {
  const [first, ...rest] = records;
  return `<article class="sp-card" data-sci="${e(sp.sci)}">
    <img class="main" src="data/species-images/${e(first.img)}" alt="${e(sp.fr || sp.sci)}" loading="lazy" data-img="${e(first.img)}">
    ${rest.length ? `<div class="thumbs">${rest.slice(0, 3).map((r) => `<img src="data/species-images/${e(r.img)}" alt="" loading="lazy" data-img="${e(r.img)}">`).join('')}</div>` : ''}
    <div class="body"><h3>${e(sp.fr || sp.sci)}</h3><p class="sci">${e(sp.sci)}</p>${badges(sp)}
      <div class="meta">${extra}</div></div></article>`;
}

function wire(container, pool) {
  container.querySelectorAll('.sp-card').forEach((el) => {
    const sp = state.species.get(el.dataset.sci);
    el.querySelectorAll('img[data-img]').forEach((img) => img.addEventListener('click', () => {
      const rec = sp.records.find((r) => r.img === img.dataset.img);
      if (rec) { showPanel(rec); document.getElementById('sp-panel').scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }
    }));
    el.querySelector('h3').addEventListener('click', () => {
      const recs = (pool ? pool(sp) : sp.records);
      if (!recs.length) return;
      state.map.fitBounds(L.latLngBounds(recs.map((r) => [r.lat, r.lon])).pad(0.3), { maxZoom: 12 });
      showPanel(recs[0]);
      document.getElementById('sp-map').scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  });
}

function renderThreatened(limit = 24) {
  const f = state.threatFilter;
  const list = [...state.species.values()].filter((sp) => (f === 'threatened' ? RANK[sp.redlist] !== undefined && RANK[sp.redlist] <= 2
    : f === 'nt' ? sp.redlist === 'NT' : sp.protected))
    .sort((a, b) => (RANK[a.redlist] ?? 9) - (RANK[b.redlist] ?? 9) || b.records.length - a.records.length);
  const el = document.getElementById('sp-threat-gallery');
  el.innerHTML = list.length ? list.slice(0, limit).map((sp) => card(sp, sp.records, `${sp.records.length} photo(s) en Normandie`)).join('')
    + (list.length > limit ? `<div class="sp-more"><button id="sp-threat-more">Afficher ${Math.min(24, list.length - limit)} espèces de plus (${list.length} au total)</button></div>` : '')
    : '<p class="micro">Aucune espèce photographiée avec ce statut.</p>';
  wire(el);
  document.getElementById('sp-threat-more')?.addEventListener('click', () => renderThreatened(limit + 24));
}

function renderZone(limit = 24) {
  if (typeof limit !== 'number') limit = 24;
  const bounds = state.map.getBounds();
  const inZone = new Map();
  for (const { record } of state.entries) {
    if (!isShown(record) || !bounds.contains([record.lat, record.lon])) continue;
    if (!inZone.has(record.sci)) inZone.set(record.sci, []);
    inZone.get(record.sci).push(record);
  }
  const list = [...inZone.entries()].sort((a, b) => b[1].length - a[1].length);
  const nPhotos = list.reduce((t, [, r]) => t + r.length, 0);
  document.getElementById('sp-zone-title').textContent =
    `${list.length.toLocaleString('fr-FR')} espèces photographiées dans la zone affichée (${nPhotos.toLocaleString('fr-FR')} photos)`;
  const el = document.getElementById('sp-zone-gallery');
  el.innerHTML = list.length ? list.slice(0, limit).map(([sci, recs]) => card(state.species.get(sci), recs, `${recs.length} photo(s) dans la zone`)).join('')
    + (list.length > limit ? `<div class="sp-more"><button id="sp-zone-more">Afficher ${Math.min(24, list.length - limit)} espèces de plus</button></div>` : '')
    : '<p class="micro">Aucune observation photographiée dans cette zone pour les groupes cochés. Dézoomez ou déplacez la carte.</p>';
  wire(el, (sp) => inZone.get(sp.sci) || sp.records);
  document.getElementById('sp-zone-more')?.addEventListener('click', () => renderZone(limit + 24));
}

init().catch((error) => {
  $('#sp-map').innerHTML = `<p style="padding:16px;color:#8f2e2e">Données indisponibles : ${e(error.message)}</p>`;
});
