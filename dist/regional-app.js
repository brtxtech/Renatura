import {
  KEYS, DEFAULT_WEIGHTS, normaliseWeights, scoreSite, rankSites,
  formatNumber, escapeHTML as e, csvCell, sameWeights,
} from './core.js';
import { copy } from './regional-i18n.js';
// Regional explorer: every cell with data gets a score; low V is shown as a note instead of hiding the cell.
const REGIONAL_MIN_V = 0;
import { AtlasMap } from './regional-map.js';
import { methodology, pressureMethodology, sourcesPage } from './regional-documents.js';

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const state = {
  language: 'fr',
  weights: [...DEFAULT_WEIGHTS],
  metric: 'RP',
  partial: true,
  minimum: 0,
  confidence: 0,
  search: '',
  page: 'explore',
  selected: null,
  scenario: null,
  scenarioStale: false,
  busy: false,
  collection: null,
  sites: [],
  filtered: [],
  ranked: [],
  presets: [],
  connectivity: null,
  summary: null,
  catalogue: [],
  sensitivity: null,
  worker: null,
  requestId: 0,
  pending: new Map(),
};
const atlas = new AtlasMap(id => showDetail(id));
const text = key => copy[state.language][key];
const num = (value, digits = 0) => formatNumber(value, digits, state.language);
let toastTimeout;
let renderFrame;

function toast(message) {
  const element = $('#toast');
  element.textContent = message;
  element.hidden = false;
  clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => { element.hidden = true; }, 4500);
}

async function readJSON(name) {
  const response = await fetch(`data/normandie/${name}`);
  if (!response.ok) throw new Error(`Data file ${name}: HTTP ${response.status}`);
  return response.json();
}

// Precomputed light cells (tools/normandie/build_display.py): geometry + scores only; heavy per-cell details
// (evidence, metrics…) are fetched from cells_detail/<column>.json when a cell is opened. Falls back to the
// full cells.geojson when the display files have not been built or are older than it.
async function loadCells() {
  try {
    const [full, light] = await Promise.all([
      fetch('data/normandie/cells.geojson', { method: 'HEAD', cache: 'no-store' }),
      fetch('data/normandie/cells_display.geojson.gz', { method: 'HEAD', cache: 'no-store' }),
    ]);
    const tFull = Date.parse(full.headers.get('last-modified') || ''), tLight = Date.parse(light.headers.get('last-modified') || '');
    if (!light.ok || (full.ok && !(tLight >= tFull))) throw new Error('display files missing or older than cells.geojson');
    // (when cells.geojson itself is absent, e.g. a fresh clone, the light files are used as long as they exist)
    const [collection, meta] = await Promise.all([readLargeJSON('cells_display.geojson'), readJSON('cells_meta.json')]);
    for (const feature of collection.features) Object.assign(feature.properties, meta);  // shared texts, same object
    state.lightCells = true;
    return collection;
  } catch (error) {
    console.info(`Full cells file used (${error.message})`);
    state.lightCells = false;
    return readLargeJSON('cells.geojson');
  }
}

// Regional cells carry a placeholder name ("Maille régionale H1_…"): resolve the real commune from the
// cell -> commune index built by tools/normandie/build_display.py (cells_points.json). Non-blocking.
// Land acquisition cost per cell for the "Budget foncier" constraint: DVF 2021-2025 median €/ha (farmland,
// else all rural land) × cell area, in k€ (tools/normandie/price_cells.py -> buyer_cells.json). Non-blocking.
async function attachLandPrices() {
  try {
    const buyer = await readLargeJSON('buyer_cells.json');
    const price = new Map(buyer.cells.map(c => [c.id, (c.price?.agri || c.price?.rural)?.median]));
    const designations = new Map(buyer.cells.map(c => [c.id, c.designations || []]));
    for (const site of state.sites) {
      site.designations = designations.get(site.id) || [];
      site.protection_status = protectionStatus(designations.get(site.id));
      const eurHa = price.get(site.id);
      site.land_eur_ha = Number.isFinite(eurHa) ? eurHa : null;
      site.land_cost_keur = Number.isFinite(eurHa) ? eurHa * (site.area_ha || 0) / 1000 : null;
    }
    if (state.metric === 'PP') { syncControls(); recalculate(); }  // protection statuses arrived
  } catch (error) { console.warn('Land prices unavailable:', error.message); }
}

// Renatura AI predictions (pipeline/renatura_ai/run_normandie.py -> ml_predictions.json + ml_status.json).
// Map: regional rank 0-100 of each prediction (probabilities are mostly ~1 %); panel: the real value + model status.
const ML_METRICS = {
  ML_ARTIF: { field: 'artificialisation_risk', model: 'territory_forecast', fr: 'Risque d’artificialisation 2018→2024 · rang régional (0–100)', en: 'Artificialisation risk 2018→2024 · regional rank (0–100)' },
  ML_HABITAT: { field: 'habitat_loss_risk', model: 'eco_vulnerability', fr: 'Risque de perte d’habitat naturel 2018→2024 · rang régional (0–100)', en: 'Natural habitat loss risk 2018→2024 · regional rank (0–100)' },
  ML_PRESSURE: { field: 'human_pressure_estimated', model: 'human_pressure', fr: 'Pression humaine estimée (population) · rang régional (0–100)', en: 'Estimated human pressure (population) · regional rank (0–100)' },
};
const ML_STATUS_FR = { performant: 'performant', trained_exploratory: 'exploratoire', trained_not_better_than_baseline: 'ne bat pas sa référence', blocked: 'non disponible' };
async function applyPredictions(collection) {
  try {
    const [pred, status] = await Promise.all([readJSON('ml_predictions.json'), readJSON('ml_status.json')]);
    state.mlStatus = status.models || {};
    const sites = collection.features.map(f => f.properties);
    for (const [key, m] of Object.entries(ML_METRICS)) {
      const vals = sites.map(site => pred.cells[site.id]?.[m.field]).map(v => (Number.isFinite(v) ? v : null));
      const order = vals.map((v, i) => [v, i]).filter(([v]) => v !== null).sort((a, b) => a[0] - b[0]);
      const ranks = new Array(sites.length).fill(null);
      order.forEach(([, i], r) => { ranks[i] = order.length > 1 ? (100 * r) / (order.length - 1) : 50; });
      sites.forEach((site, i) => { site[key] = ranks[i]; site[`${key}_value`] = vals[i]; });
    }
    sites.forEach(site => { site.ML_PRESSURE_OBS = pred.cells[site.id]?.human_pressure_observed_2017 ?? null; });
    $$('#metric option[data-ml]').forEach(o => { o.disabled = false; });
    if (ML_METRICS[state.metric]) recalculate();
    if (state.selected) showDetail(state.selected, false);
  } catch (error) {
    console.info(`Model predictions unavailable (${error.message})`);
  }
}

function mlBlock(site, en) {
  if (!state.mlStatus || site.ML_ARTIF_value === undefined) return '';
  const st = k => ML_STATUS_FR[state.mlStatus[k]?.status] || '—';
  const pct = v => (Number.isFinite(v) ? `${num(100 * v, 1)} %` : '—');
  const dens = v => (Number.isFinite(v) ? `${num(10 ** v - 1)} hab/km²` : '—');
  return `<div class="ml-block" style="margin-top:10px;padding:10px;border:1px solid #dde4d8;border-radius:10px;background:#fbfcf8">
    <strong style="font-size:13px">${en ? 'Renatura AI models' : 'Modèles IA Renatura'}</strong> <a class="micro" href="modeles.html">${en ? 'how they learn' : 'comment ils apprennent'}</a>
    <dl class="detail-raw" style="margin:6px 0 0">
      <dt>${en ? 'Artificialisation risk 2018→2024' : 'Risque d’artificialisation 2018→2024'}</dt><dd>${pct(site.ML_ARTIF_value)} <span class="micro">· ${st('territory_forecast')}</span></dd>
      <dt>${en ? 'Natural habitat loss risk 2018→2024' : 'Risque de perte d’habitat naturel'}</dt><dd>${pct(site.ML_HABITAT_value)} <span class="micro">· ${st('eco_vulnerability')}</span></dd>
      <dt>${en ? 'Human pressure (estimated / INSEE 2017)' : 'Pression humaine (estimée / INSEE 2017)'}</dt><dd>${dens(site.ML_PRESSURE_value)} / ${dens(site.ML_PRESSURE_OBS)} <span class="micro">· ${st('human_pressure')}</span></dd>
    </dl>
    <p class="micro" style="margin:4px 0 0">${en ? 'Probabilities of events observed by CORINE (25 ha units); about 1 % of cells change in 6 years.' : 'Probabilités d’événements observés par CORINE (unité 25 ha) ; environ 1 % des mailles changent en 6 ans.'}</p></div>`;
}

async function applyCommuneNames(collection) {
  try {
    const points = await readLargeJSON('cells_points.json');
    const index = new Map(points.id.map((id, i) => [id, points.commune[i]]));
    for (const { properties: site } of collection.features) {
      const c = points.communes[index.get(site.id)];
      if (c && (!site.commune || site.commune.startsWith('Maille'))) {
        site.commune = c.name;
        site.commune_codes = [c.insee];
      }
    }
    renderRanking();
    renderResult();
    if (state.selected) showDetail(state.selected, false);
  } catch (error) {
    console.info(`Commune names unavailable (${error.message})`);
  }
}

const detailChunks = new Map();
async function ensureDetail(site) {
  if (!state.lightCells || site._detail) return;
  const key = String(site.id).split('_')[1] ?? 'misc';
  if (!detailChunks.has(key)) detailChunks.set(key, readJSON(`cells_detail/${key}.json`).catch(() => ({})));
  Object.assign(site, (await detailChunks.get(key))[site.id] || {});
  site._detail = true;
}

// Large files: prefer the gzip copy (84 MB -> ~5 MB) when the browser can unzip it and the copy is not
// older than the plain file (another build may have rewritten only the plain file). Falls back silently.
async function readLargeJSON(name) {
  try {
    if (typeof DecompressionStream === 'undefined') throw new Error('no DecompressionStream');
    const [plain, packed] = await Promise.all([
      fetch(`data/normandie/${name}`, { method: 'HEAD', cache: 'no-store' }),
      fetch(`data/normandie/${name}.gz`, { method: 'HEAD', cache: 'no-store' }),
    ]);
    const plainTime = Date.parse(plain.headers.get('last-modified') || '');
    const packedTime = Date.parse(packed.headers.get('last-modified') || '');
    // use the gzip copy if the plain file is absent (it is not versioned: > 100 MB) or not newer than the copy
    if (!packed.ok || (plain.ok && !(packedTime >= plainTime))) throw new Error('gzip copy missing or stale');
    const response = await fetch(`data/normandie/${name}.gz`, { cache: 'no-store' });
    const bytes = new Uint8Array(await response.arrayBuffer());
    // A server may already have decoded it (Content-Encoding: gzip): check the gzip magic number.
    const isGzip = bytes[0] === 0x1f && bytes[1] === 0x8b;
    const text = isGzip
      ? await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).text()
      : new TextDecoder().decode(bytes);
    return JSON.parse(text);
  } catch (error) {
    console.info(`${name}: plain file used (${error.message})`);
    return readJSON(name);
  }
}

function loadURL() {
  const params = new URLSearchParams(location.search);
  if (params.get('lang') === 'en') state.language = 'en';
  const weights = params.get('w')?.split(',').map(Number);
  if (weights) {
    try { state.weights = normaliseWeights(weights); } catch { /* Keep documented defaults. */ }
  }
  const metric = params.get('metric');
  if (['RP', 'PP', 'V', 'D', 'P', 'CTX', 'O', 'betweenness', 'EXPLORATORY', 'ML_ARTIF', 'ML_HABITAT', 'ML_PRESSURE'].includes(metric)) state.metric = metric;
  if (params.has('partial')) state.partial = params.get('partial') === '1';
  for (const key of ['minimum', 'confidence']) {
    const value = Number(params.get(key));
    if (Number.isFinite(value) && value >= 0 && value <= 100) state[key] = value;
  }
  state.search = (params.get('q') || '').slice(0, 100);
}

function saveURL() {
  const params = new URLSearchParams();
  params.set('lang', state.language);
  params.set('w', state.weights.map(v => v.toFixed(4)).join(','));
  params.set('metric', state.metric);
  params.set('partial', state.partial ? '1' : '0');
  params.set('minimum', state.minimum);
  params.set('confidence', state.confidence);
  if (state.search) params.set('q', state.search);
  history.replaceState(null, '', `${location.pathname}?${params}`);
}

function applyLanguage() {
  document.documentElement.lang = state.language;
  $$('[data-i18n]').forEach(element => {
    const key = element.dataset.i18n;
    if (key === 'headline' || key === 'scenarioHelp') element.innerHTML = text(key);
    else element.textContent = text(key);
  });
  $('#language').textContent = state.language === 'fr' ? 'EN' : 'FR';
  $('#search').placeholder = text('searchPlaceholder');
  [...$('#constraint').options].forEach((option, index) => {
    option.textContent = text('constraintOptions')[index];
  });
  renderWeights();
  if (state.summary) {
    renderStatistics();
    renderRegionalCatalogue();
    if (state.summary.regional_readiness) {
      const a=state.summary.regional_readiness;
      $('#regional-counts').textContent += ` Critères complets : ${a.all_four_criteria_cells}/${state.sites.length} mailles. Graphe calculé : ${a.connectivity.cells}/${state.sites.length} mailles ; ${a.connectivity.corridors} corridors.`;
    }
    $('#lambda').dispatchEvent(new Event('input'));
    renderPresets();
    renderDocuments();
    renderRanking();
    renderResult();
    if (state.selected) showDetail(state.selected, false);
  }
  saveURL();
}

function renderWeights() {
  const normal = normaliseWeights(state.weights);
  $('#weights').innerHTML = KEYS.map((key, index) => `
    <div class="weight-row ${index > 1 ? 'weight-unavailable' : ''}">
      <label class="range-title" for="weight-${key}">
        <span>${key} · ${e(text('breakdown')[index])}</span>
        <output>${num(normal[index] * 100)}%</output>
      </label>
      <input id="weight-${key}" data-weight="${index}" type="range" min="0" max="100" step="1" value="${Math.round(state.weights[index] * 100)}" aria-label="${e(text('breakdown')[index])}">
    </div>`).join('');
  $$('[data-weight]').forEach(input => input.addEventListener('input', event => {
    const index = Number(event.target.dataset.weight);
    const candidate = [...state.weights];
    candidate[index] = Number(event.target.value) / 100;
    if (candidate.every(value => value === 0)) {
      event.target.value = Math.round(state.weights[index] * 100);
      return;
    }
    state.weights = candidate;
    const normalized = normaliseWeights(candidate);
    $$('#weights output').forEach((output, i) => { output.textContent = `${num(normalized[i] * 100)}%`; });
    invalidateScenario();
    scheduleRender();
  }));
}

function renderStatistics() {
  $('#stat-cells').textContent = num(state.summary.cell_count);
  $('#stat-area').innerHTML = `${num(state.summary.area_ha / 100)} <small>km²</small>`;
  $('#stat-hedges').innerHTML = `${num(state.summary.hedge_2016_km)} <small>km</small>`;
  $('#regional-coverage').textContent = `${num(state.summary.coverage_min/25)}–${num(state.summary.coverage_max/25)} / 4`;
}


// Índice exploratorio: no modifica V, D, P, O ni el RP original.
function exploratoryIndex(site) {
  const valid = value =>
    Number.isFinite(value) && value >= 0 && value <= 100;

  const pressure = valid(site.P) ? site.P :
    valid(site.P_preview) ? site.P_preview : null;

  const values = [site.V, site.D, pressure, site.O];
  let numerator = 0;
  let denominator = 0;

  values.forEach((value, index) => {
    const weight = state.weights[index];
    if (valid(value) && Number.isFinite(weight) && weight > 0) {
      numerator += weight * value;
      denominator += weight;
    }
  });

  return denominator > 0 ? numerator / denominator : null;
}

// ---------- Protection priority (PP): where valuable, still-intact nature is under human pressure.
// Same formula as tools/normandie/regional_model/scoring.py protection_score(): V × (1 − D/100) × P/100,
// then expressed as a percentile rank over Normandy (0–100) so the map uses the full colour range.
// Independent of the RP weights. Protection status comes from the designations touching each cell (buyer_cells.json).
const STRONG = ['Réserve naturelle nationale', 'Réserve naturelle régionale', 'APB'];
const CONTRACT = ['Natura 2000 ZSC', 'Natura 2000 ZPS', 'ORE existante'];
const INVENTORY = ['ZNIEFF 1', 'ZNIEFF 2'];
const PROTECTION_LABEL = {
  strong: ['Protection forte (réserve, APB)', 'Strong protection (reserve, biotope order)'],
  contract: ['Natura 2000 / ORE', 'Natura 2000 / conservation easement'],
  inventory: ['Inventaire seul (ZNIEFF)', 'Inventory only (ZNIEFF)'],
  none: ['Aucune protection', 'No protection'],
  unknown: ['Statut inconnu', 'Unknown status'],
};
const GAP_THRESHOLD = 70;  // PP ≥ 70 (top 30 % of Normandy) without regulatory or contractual protection = protection gap
const protectionLabel = site => PROTECTION_LABEL[site.protection_status || 'unknown'][state.language === 'en' ? 1 : 0];
const isGap = site => Number.isFinite(site.PP) && site.PP >= GAP_THRESHOLD && ['none', 'inventory'].includes(site.protection_status);
function computeProtection() {
  const rows = state.sites.map(site => {
    const ok = [site.V, site.D, site.P].every(Number.isFinite);
    return [site, ok ? site.V * (1 - site.D / 100) * site.P / 100 : null];
  });
  const valid = rows.filter(([, raw]) => raw !== null).sort((a, b) => a[1] - b[1]);
  const n = valid.length;
  rows.forEach(([site]) => { site.PP = null; site.PP_raw = null; });
  valid.forEach(([site, raw], i) => { site.PP_raw = raw; site.PP = n > 1 ? 100 * i / (n - 1) : 100; });
}
function protectionStatus(designations) {
  if (!designations) return 'unknown';
  if (designations.some(d => STRONG.includes(d))) return 'strong';
  if (designations.some(d => CONTRACT.includes(d))) return 'contract';
  if (designations.some(d => INVENTORY.includes(d))) return 'inventory';
  return 'none';
}
function rankForView(sites) {
  if (state.metric !== 'PP') return rankSites(sites, state.weights, state.partial, REGIONAL_MIN_V);
  return sites.filter(site => Number.isFinite(site.PP)).map(site => ({ ...site, score: site.PP }))
    .sort((a, b) => b.PP - a.PP || a.id.localeCompare(b.id));
}

function metricValue(site) {
  if (state.metric === 'EXPLORATORY') return exploratoryIndex(site);
  if (state.metric === 'RP') return scoreSite(site, state.weights, state.partial, REGIONAL_MIN_V).score;
  if (state.metric === 'PP') return site.PP;
  if (state.metric === 'betweenness') return Number.isFinite(site.betweenness) ? site.betweenness * 100 : null;
  if (state.metric === 'CTX') return site.context_score;
  return site[state.metric];
}

function recalculate() {
  if (!state.collection) return;
  const query = state.search.toLocaleLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  state.filtered = state.sites.filter(site => {
    const name = `${site.commune} ${site.id} ${site.commune_codes.join(' ')}`
      .toLocaleLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    const value = metricValue(site);
    return (!query || name.includes(query)) && site.coverage >= state.confidence
      && (state.minimum === 0 || (Number.isFinite(value) && value >= state.minimum))
      && (state.metric !== 'PP' || !state.gapsOnly || isGap(site));
  });
  // The scenario lab always works on restoration priority; the ranking table follows the mapped view.
  state.ranked = rankSites(state.filtered, state.weights, state.partial, REGIONAL_MIN_V);
  state.viewRanked = rankForView(state.filtered);
  const filteredIds = new Set(state.filtered.map(site => site.id));
  const selected = new Set(state.scenario && !state.scenarioStale ? state.scenario.selected : []);
  const collection = {
    type: 'FeatureCollection',
    features: state.collection.features.filter(feature => filteredIds.has(feature.properties.id))
      .map(feature => {
        const display = metricValue(feature.properties);
        return { ...feature, properties: { ...feature.properties,
          display: Number.isFinite(display) ? display : 0,
          missing: !Number.isFinite(display), selected: selected.has(feature.properties.id) } };
      }),
  };
  atlas.update(collection);
  $('#visible-count').textContent = `${num(state.filtered.length)} / ${num(state.sites.length)} ${text('units').toLowerCase()}`;
  $('#legend-title').textContent = ML_METRICS[state.metric] ? ML_METRICS[state.metric][state.language === 'en' ? 'en' : 'fr'] : state.metric === 'PP' ? (state.language === 'en' ? 'Protection priority · percentile' : 'Priorité de protection · rang 0–100') : state.metric === 'EXPLORATORY' ? 'Indice exploratoire · données disponibles' : state.metric === 'RP' ? text('score') : state.metric === 'CTX' ? 'Contexte documentaire · pas un score écologique' : state.metric;
  renderRanking();
  if (state.selected) showDetail(state.selected, false);
  updateSensitivityContext();
  saveURL();
  return collection;
}

function scheduleRender() {
  cancelAnimationFrame(renderFrame);
  renderFrame = requestAnimationFrame(recalculate);
}

function renderRanking() {
  const pp = state.metric === 'PP', en = state.language === 'en';
  const head = $('#ranking-body').closest('table').querySelector('thead tr');
  head.innerHTML = pp
    ? `<th>#</th><th>${e(text('commune'))}</th><th>PP</th><th>V</th><th>D</th><th>P</th><th>${en ? 'Protection' : 'Protection actuelle'}</th>`
    : `<th>#</th><th>${e(text('commune'))}</th><th>RP</th><th>V</th><th>D</th><th>${e(text('coverage'))}</th><th>ha</th>`;
  const rows = (pp ? state.viewRanked : state.ranked) || [];
  $('#ranking-body').innerHTML = rows.slice(0, 20).map((site, index) => pp ? `
    <tr>
      <td>${index + 1}</td>
      <td><button data-select="${e(site.id)}">${e(site.commune)}<small>${e(site.id)}</small></button></td>
      <td>${num(site.PP, 1)}</td>
      <td>${num(site.V, 1)}</td>
      <td>${num(site.D, 1)}</td>
      <td>${num(site.P, 1)}</td>
      <td>${isGap(site) ? `<b style="color:#9a3412">${en ? 'Gap' : 'Lacune'}</b> · ` : ''}${e(protectionLabel(site))}</td>
    </tr>` : `
    <tr>
      <td>${index + 1}</td>
      <td><button data-select="${e(site.id)}">${e(site.commune)}<small>${e(site.id)}</small></button></td>
      <td>${num(site.score, 1)}*</td>
      <td>${num(site.V, 1)}</td>
      <td>${num(site.D, 1)}</td>
      <td>${num(site.coverage)}%</td>
      <td>${num(site.area_ha, 1)}</td>
    </tr>`).join('') || `<tr><td colspan="7">${e(text('noSelection'))}</td></tr>`;
  $$('[data-select]').forEach(button => button.addEventListener('click', () => showDetail(button.dataset.select)));
}

function protectionBlock(site) {
  const en = state.language === 'en';
  if (!Number.isFinite(site.PP)) return '';
  const des = (site.designations || []).filter(d => [...STRONG, ...CONTRACT, ...INVENTORY, 'Parc naturel régional'].includes(d));
  return `<div class="protection-block ${isGap(site) ? 'is-gap' : ''}">
    <div class="range-title"><span>${en ? 'Protection priority (PP)' : 'Priorité de protection (PP)'}</span><strong>${num(site.PP, 0)} /100</strong></div>
    <p class="micro">${en ? 'Status' : 'Statut actuel'} : <b>${e(protectionLabel(site))}</b>${des.length ? ` — ${des.map(e).join(', ')}` : ''}</p>
    ${isGap(site) ? `<p class="micro"><b>${en ? 'Protection gap' : 'Lacune de protection'}</b> : ${en ? 'valuable, still intact nature under pressure, without regulatory or contractual protection.' : 'nature de valeur, encore peu dégradée et sous pression, sans protection réglementaire ni contractuelle.'}</p>` : ''}
    <p class="micro">PP = V ${num(site.V, 0)} × (1 − D ${num(site.D, 0)}/100) × P ${num(site.P, 0)}/100 = ${num(site.PP_raw, 1)} → ${en ? 'rank' : 'rang'} ${num(site.PP, 0)}/100 ${en ? 'in Normandy' : 'en Normandie'}.</p>
  </div>`;
}

async function showDetail(id, fly = true) {
  const feature = state.collection.features.find(feature => feature.properties.id === id);
  if (!feature) return;
  state.selected = id;
  const site = feature.properties;
  await ensureDetail(site);  // light mode: evidence & metrics loaded for this cell only
  if (state.selected !== id) return;  // another cell was clicked meanwhile
  const score = scoreSite(site, state.weights, state.partial, REGIONAL_MIN_V);
  const panel = $('#detail-panel');
  const en = state.language === 'en';
  panel.innerHTML = `
    <button class="close-detail" aria-label="${en ? 'Close details' : 'Fermer les détails'}">×</button>
    <div class="eyebrow">${e(site.id)}</div>
    <h3>${e(site.commune)}</h3>
    <p class="micro">${num(site.area_ha, 1)} ha · ${num(site.coverage)}% ${text('coverage').toLowerCase()}</p>
    <div class="detail-score">${num(score.score, 1)} <small>/100 · ${text('score')}</small></div>
    ${protectionBlock(site)}
    ${Number.isFinite(site.V) && site.V < 10 ? `<p class="micro" style="color:#9a5b16">${en ? 'Low ecological value (V < 10): little natural structure left in this cell.' : 'Valeur écologique faible (V < 10) : peu de structure naturelle restante dans cette maille.'}</p>` : ''}
    ${mlBlock(site, en)}
    ${KEYS.map((key, i) => `
      <div class="breakdown-row">
        <div><span>${key} · ${e(text('breakdown')[i])}</span><strong>${num(site[key])}</strong></div>
        <div class="breakdown-track ${Number.isFinite(site[key]) ? '' : 'is-missing'}" title="${Number.isFinite(site[key]) ? '' : (en ? 'No data for this cell' : 'Donnée absente pour cette maille')}">${Number.isFinite(site[key]) ? `<i style="width:${site[key]}%"></i>` : ''}</div>
      </div>`).join('')}
    <p class="micro">${en ? 'Displayed criteria use observations covering this cell. Inspect provenance and missing criteria below.' : 'Les critères affichés sont calculés uniquement à partir des observations couvrant cette maille. Consulter les sources et les critères manquants ci-dessous.'}</p>
    ${[site.hedge_1947_m, site.hedge_2010_m, site.hedge_2016_m, site.woodland_ha].some(Number.isFinite) ? '' : '<!-- no pilot hedge observation in this cell -->'}
    <dl class="detail-raw" ${[site.hedge_1947_m, site.hedge_2010_m, site.hedge_2016_m, site.woodland_ha].some(Number.isFinite) ? '' : 'hidden'}>
      <dt>${en ? 'Hedgerows' : 'Haies'} 1947</dt><dd>${num(site.hedge_1947_m)} m</dd>
      <dt>${en ? 'Hedgerows' : 'Haies'} ${e(site.observation_years?.before || 2010)}</dt><dd>${num(site.hedge_2010_m)} m</dd>
      <dt>${en ? 'Hedgerows' : 'Haies'} ${e(site.observation_years?.after || 2016)}</dt><dd>${num(site.hedge_2016_m)} m</dd>
      <dt>${en ? 'Woodland' : 'Bois'} ${e(site.observation_years?.after || 2016)}</dt><dd>${num(site.woodland_ha, 1)} ha</dd>
      <dt>${en ? 'Betweenness' : 'Intermédiarité'}</dt><dd>${num(site.betweenness, 4)}</dd>
    </dl>
    ${[site.hedge_1947_m, site.hedge_2010_m, site.hedge_2016_m, site.woodland_ha].some(Number.isFinite) ? '<p class="micro">DREAL Normandie · 1947 / 2010 / 2016 · Licence Ouverte 2.0</p>' : `<p class="micro">${en ? 'Betweenness' : 'Intermédiarité'} : ${num(site.betweenness, 4)}</p>`}`;
  const evidence = site.evidence || {};
  panel.insertAdjacentHTML('beforeend', `<div class="regional-provenance"><h4>Sources réellement utilisées</h4>${KEYS.map(key => `<p><b>${key}</b> : ${Number.isFinite(site[key]) ? num(site[key],1) : 'absent'}</p><ul>${(evidence[key] || []).map(row => `<li>${e(state.catalogue.find(s=>s.id===row.sourceId)?.title || row.sourceId)} · ${e(row.year)} · ${e(row.metric)} : ${num(row.value,2)} ${e(row.unit)}</li>`).join('') || '<li>Pas de mesure validée couvrant cette maille.</li>'}</ul>`).join('')}<p class="micro">Référence : ${e(site.normalization_reference || state.summary.site)}. Les valeurs régionales ne sont pas extrapolées depuis Bocages.</p></div>`);
  if(Number.isFinite(site.context_score)) panel.insertAdjacentHTML('beforeend', `<p class="micro"><b>Contexte documentaire : ${num(site.context_score,1)}%</b><br>${num(site.context_layers)}/354 couches catalogue · ${num(site.context_themes)}/14 thèmes représentés sur la maille atlas 5×5 km englobante. Densité documentaire, pas un score écologique ; une absence de résultat ne prouve pas une absence d’enjeu.</p>`);
  panel.hidden = false;
  panel.querySelector('.close-detail').addEventListener('click', () => {
    panel.hidden = true;
    state.selected = null;
  });
  if (fly) atlas.focus(feature);
}

function renderPresets() {
  $('#presets').innerHTML = state.presets.map((preset, index) => `
    <button class="preset-card ${state.scenario?.id === preset.id && !state.scenarioStale ? 'active' : ''}" data-preset="${index}">
      <span><strong>${e(state.language === 'fr' ? preset.name : ['Focused intervention', 'Balanced network', 'Territorial ambition', '500 ha envelope', '€5M land budget'][index])}</strong>
      <small>${num(preset.budget)} ${preset.mode === 'sites' ? 'sites' : preset.mode === 'hectares' ? 'ha' : 'k€'} · ${preset.status === 'OPTIMAL' ? 'ILP ✓' : 'ILP'}</small></span>
      <span>↗</span>
    </button>`).join('');
  $$('[data-preset]').forEach(button => button.addEventListener('click', () => {
    cancelWorker();
    const preset = state.presets[Number(button.dataset.preset)];
    state.weights = [...preset.weights];
    state.partial = preset.allow_partial;
    state.search = '';
    state.minimum = 0;
    state.confidence = 0;
    state.metric = 'RP';
    state.scenario = { ...preset, scope: state.sites.map(s => s.id) };
    state.scenarioStale = false;
    $('#constraint').value = preset.mode;
    $('#budget').value = preset.budget;
    $('#lambda').value = preset.connectivity_weight;
    syncControls();
    renderWeights();
    renderPresets();
    renderResult();
    recalculate();
    toast(text('presetReset'));
  }));
}

function syncControls() {
  $('#search').value = state.search;
  $('#minimum').value = state.minimum;
  $('#confidence').value = state.confidence;
  $('#metric').value = state.metric;
  $('#partial').checked = state.partial;
  $('#minimum-value').textContent = state.minimum;
  $('#confidence-value').textContent = `${state.confidence}%`;
  $('#lambda-value').textContent = Number($('#lambda').value).toFixed(2);
  $('#budget-unit').textContent = $('#constraint').value === 'sites' ? 'sites' : $('#constraint').value === 'hectares' ? 'ha' : 'k€';
  $$('[data-metric]').forEach(button => button.classList.toggle('active', button.dataset.metric === state.metric));
  $('#protection-tools').hidden = state.metric !== 'PP';
  if (state.metric === 'PP' && state.sites?.length) {
    const scored = state.sites.filter(s => Number.isFinite(s.PP)), high = scored.filter(s => s.PP >= GAP_THRESHOLD);
    const by = k => high.filter(s => s.protection_status === k).length;
    const en = state.language === 'en';
    $('#protection-summary').innerHTML = high.some(s => s.protection_status) ? `${en ? 'Top 30 % (PP ≥ 70)' : 'Les 30 % les plus prioritaires (PP ≥ 70)'} : <b>${num(high.length)}</b> ${en ? 'cells' : 'mailles'} —
      ${num(by('strong'))} ${en ? 'strongly protected' : 'en protection forte'}, ${num(by('contract'))} Natura 2000 / ORE, ${num(by('inventory'))} ${en ? 'ZNIEFF only' : 'en ZNIEFF seule'},
      <b>${num(by('none'))}</b> ${en ? 'without any designation' : 'sans aucune désignation'}. <b>${num(high.filter(isGap).length)}</b> ${en ? 'protection gaps' : 'lacunes de protection'}.` : (en ? 'Loading protection statuses…' : 'Chargement des statuts de protection…');
  }
}

function invalidateScenario() {
  if (state.busy) cancelWorker();
  if (state.scenario) {
    state.scenarioStale = true;
    renderResult();
    renderPresets();
  }
}

function renderResult() {
  const result = state.scenario;
  if (!result) return;
  $('#export-scenario').hidden = state.scenarioStale;
  if (state.scenarioStale) {
    $('#scenario-result').innerHTML = `<div class="coverage-note"><span>!</span><p>${text('stale')}</p></div>`;
    return;
  }
  const peak = Math.max(result.objective, result.baseline_objective, 1);
  $('#scenario-result').innerHTML = `
    <span class="result-status">${result.status === 'OPTIMAL' ? text('optimal') : text('feasible')}</span>
    <div class="result-number">${result.selected.length} <small>${text('selected')}</small></div>
    <div class="result-grid">
      <div><span>${text('area')}</span><strong>${num(result.area_ha, 1)} ha</strong></div>
      <div><span>${text('gain')}</span><strong>${result.gain_percent === null ? '—' : `${result.gain_percent >= 0 ? '+' : ''}${num(result.gain_percent, 1)}%`}</strong></div>
      <div><span>${text('budgetUsed')}</span><strong>${num(result.used, 1)} / ${num(result.budget)}</strong></div>
      <div><span>${text('connections')}</span><strong>${num(result.connectivity_total, 1)}</strong></div>
    </div>
    <div class="range-title"><span>${text('objective')}</span><strong>${num(result.objective, 1)}</strong></div>
    <div class="comparison-bar"><i style="width:${result.objective / peak * 100}%"></i></div>
    <div class="range-title"><span>${text('baseline')}</span><strong>${num(result.baseline_objective, 1)}</strong></div>
    <div class="comparison-bar"><i style="width:${result.baseline_objective / peak * 100}%;background:#a4b59b"></i></div>
    <p class="micro">${text('upper')}: ${num(result.upper_bound, 1)} · ${text('gap')}: ${num(result.gap_percent, 1)}%${result.eligible != null ? ` · ${num(result.eligible)} ${state.language === 'fr' ? 'mailles éligibles' : 'eligible cells'} (≥ ${num(result.min_area)} ha)` : ''}</p>
    ${landCostLine(result)}
    ${selectedSitesList(result)}
    <div class="coverage-note"><span>!</span><p>${text('partialNotice')}</p></div>`;
  $$('#scenario-result [data-site]').forEach(button => button.addEventListener('click', () => showDetail(button.dataset.site)));
}

function landCostLine(result) {
  const lookup = new Map(state.sites.map(site => [site.id, site]));
  const costs = result.selected.map(id => lookup.get(id)?.land_cost_keur).filter(Number.isFinite);
  if (!costs.length) return '';
  const total = costs.reduce((a, b) => a + b, 0);
  return `<p class="micro">${state.language === 'fr' ? 'Coût foncier indicatif (DVF)' : 'Indicative land cost (DVF)'} : <b>${num(total / 1000, 1)} M€</b>${costs.length < result.selected.length ? ` (${costs.length}/${result.selected.length})` : ''}</p>`;
}

// The retained cells, best score first: commune, cell id, priority and criteria. Click = open on the map.
function selectedSitesList(result) {
  const lookup = new Map(state.sites.map(site => [site.id, site]));
  const weights = result.weights || state.weights;
  const rows = result.selected.map(id => lookup.get(id)).filter(Boolean)
    .map(site => ({ site, score: scoreSite(site, weights, result.allow_partial ?? state.partial, REGIONAL_MIN_V).score }))
    .sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
  if (!rows.length) return '';
  const cell = v => Number.isFinite(v) ? num(v) : '—';
  return `<div class="selected-sites">
    <div class="range-title"><span>${text('selectedList')}</span><strong>${rows.length}</strong></div>
    <p class="micro">${text('selectedListHelp')}</p>
    <ol>${rows.map(({ site, score }, i) => `<li><button type="button" data-site="${e(site.id)}">
      <span class="site-rank">${i + 1}</span>
      <span class="site-name">${e(site.commune)}<small>${e(site.id)} · ${num(site.area_ha, 1)} ha</small></span>
      <span class="site-score"><strong>${cell(score)}</strong><small>V ${cell(site.V)} · D ${cell(site.D)} · P ${cell(site.P)} · O ${cell(site.O)}</small></span>
    </button></li>`).join('')}</ol></div>`;
}

function startWorker() {
  if (state.worker) return;
  state.worker = new Worker(new URL('./worker.js?v=20261111-scenarios2', import.meta.url), { type: 'module' });
  state.worker.onmessage = event => {
    const message = event.data;
    const pending = state.pending.get(message.requestId);
    if (!pending) return;
    state.pending.delete(message.requestId);
    if (message.error) pending.reject(new Error(message.error));
    else pending.resolve(message.result);
  };
  state.worker.onerror = event => {
    for (const item of state.pending.values()) item.reject(new Error(event.message || 'Worker failed'));
    state.pending.clear();
    state.worker?.terminate();
    state.worker = null;
  };
}

function requestWorker(type, payload) {
  startWorker();
  const requestId = ++state.requestId;
  return new Promise((resolve, reject) => {
    state.pending.set(requestId, { resolve, reject });
    state.worker.postMessage({ type, payload, requestId });
  });
}

function cancelWorker() {
  state.worker?.terminate();
  state.worker = null;
  for (const item of state.pending.values()) item.reject(new Error('CANCELLED'));
  state.pending.clear();
  state.busy = false;
  $('#run-scenario').disabled = false;
  $('#cancel-scenario').hidden = true;
}

async function runScenario() {
  const budget = Number($('#budget').value);
  if (!Number.isFinite(budget) || budget < 0 || budget > 100000) {
    toast('Budget: 0–100000');
    return;
  }
  if (!state.ranked.length) {
    toast(text('noSelection'));
    return;
  }
  state.busy = true;
  $('#run-scenario').disabled = true;
  $('#cancel-scenario').hidden = false;
  try {
    const scope = state.filtered.map(site => site.id);
    const result = await requestWorker('solve', {
      sites: state.filtered,
      paths: state.connectivity.paths,
      weights: [...state.weights],
      partial: state.partial,
      mode: $('#constraint').value,
      budget,
      minArea: Number($('#min-area').value) || 0,
      lambda: Number($('#lambda').value),
    });
    state.scenario = { ...result, scope };
    state.scenarioStale = false;
    renderPresets();
    renderResult();
    recalculate();
  } catch (error) {
    if (error.message !== 'CANCELLED') toast(error.message);
  } finally {
    state.busy = false;
    $('#run-scenario').disabled = false;
    $('#cancel-scenario').hidden = true;
  }
}

function download(name, contents, type = 'application/json') {
  const blob = new Blob([typeof contents === 'string' ? contents : JSON.stringify(contents, null, 2)], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

function exportRanking(type) {
  const top = (state.metric === 'PP' ? state.viewRanked : state.ranked).slice(0, 20);
  if (type === 'csv') {
    const keys = state.metric === 'PP' ? ['id', 'commune', 'PP', 'PP_raw', 'V', 'D', 'P', 'protection_status', 'area_ha'] : ['id', 'commune', 'score', 'V', 'D', 'P', 'O', 'coverage', 'area_ha', 'partial'];
    const rows = [keys.map(csvCell).join(','), ...top.map(site => keys.map(key => csvCell(site[key])).join(','))];
    download('renatura-top20.csv', '\uFEFF' + rows.join('\r\n'), 'text/csv;charset=utf-8');
  } else {
    const lookup = new Map(top.map(site => [site.id, site]));
    download('renatura-top20.geojson', {
      type: 'FeatureCollection',
      metadata: { weights: normaliseWeights(state.weights), partial: state.partial, site: state.summary.site },
      features: state.collection.features.filter(f => lookup.has(f.properties.id))
        .map(f => ({ ...f, properties: lookup.get(f.properties.id) })),
    }, 'application/geo+json');
  }
}

function updateSensitivityContext() {
  const element = $('#sensitivity-context');
  if (!element || !state.sensitivity) return;
  const matches = sameWeights(state.weights, state.sensitivity.weights)
    && state.partial === state.sensitivity.allow_partial;
  element.textContent = (state.language === 'fr'
    ? (matches ? 'Poids identiques à la vue actuelle. ' : 'Attention : poids différents de la vue actuelle. ')
    : (matches ? 'Weights match the current view. ' : 'Warning: weights differ from the current view. '))
    + (state.language === 'fr' ? 'Analyse sur toutes les mailles régionales chargées, indépendamment des filtres.' : 'Analysis covers all loaded regional cells, independently of filters.');
}

function renderDocuments() {
  $('#method-page').innerHTML = methodology(state.language, state.sensitivity, state.sites, state.summary);
  const pressurePage = $('#pressure-page');
  if (pressurePage) pressurePage.innerHTML = pressureMethodology(state.language, state.summary, state.layerScoring);
  $('#sources-page').innerHTML = sourcesPage(state.language, state.catalogue, state.summary);
  updateSensitivityContext();
  $('#live-sensitivity').addEventListener('click', async event => {
    if (state.busy) return toast(state.language === 'fr' ? 'Un calcul est déjà en cours.' : 'A calculation is already running.');
    event.target.disabled = true;
    try {
      const result = await requestWorker('sensitivity', {
        sites: state.sites, weights: [...state.weights], partial: state.partial,
      });
      state.sensitivity = result;
      renderDocuments();
    } catch (error) {
      toast(error.message);
      event.target.disabled = false;
    }
  });
  $('#export-sensitivity').addEventListener('click', () => download('renatura-sensitivity.json', state.sensitivity));
  $('#cache-offline').addEventListener('click', async event => {
    event.target.disabled = true;
    try {
      if (!('serviceWorker' in navigator)) throw new Error('Service worker unavailable');
      const registration = await navigator.serviceWorker.ready;
      const worker = registration.active;
      if (!worker) throw new Error('Reload once to activate offline caching.');
      const channel = new MessageChannel();
      const result = new Promise((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error('Offline preparation timed out')), 60000);
        channel.port1.onmessage = event => {
          clearTimeout(timeout);
          event.data.error ? reject(new Error(event.data.error)) : resolve();
        };
      });
      worker.postMessage({ type: 'CACHE_LAYERS' }, [channel.port2]);
      await result;
      toast(state.language === 'fr' ? 'Couches prêtes pour une utilisation hors ligne.' : 'Layers ready for offline use.');
    } catch (error) {
      toast(error.message);
    } finally {
      event.target.disabled = false;
    }
  });
}

function changePage(page) {
  state.page = page;
  $('#workspace').hidden = ['method', 'pressure', 'sources'].includes(page);
  $('#method-page').hidden = page !== 'method';
  if ($('#pressure-page')) $('#pressure-page').hidden = page !== 'pressure';
  $('#sources-page').hidden = page !== 'sources';
  $$('[data-page]').forEach(button => button.classList.toggle('active', button.dataset.page === page));
  if (page === 'explore' || page === 'scenarios') atlas.resize();
  if (page === 'scenarios') $('#scenario-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  else window.scrollTo({ top: 0, behavior: 'instant' });
}

function wireEvents() {
  $$('[data-page]').forEach(button => button.addEventListener('click', () => changePage(button.dataset.page)));
  $('#language').addEventListener('click', () => {
    state.language = state.language === 'fr' ? 'en' : 'fr';
    applyLanguage();
    recalculate();
  });
  $('#share').addEventListener('click', async () => {
    saveURL();
    try {
      await navigator.clipboard.writeText(location.href);
      toast(text('copied'));
    } catch {
      toast(location.href);
    }
  });
  $('#search').addEventListener('input', event => {
    state.search = event.target.value;
    invalidateScenario();
    scheduleRender();
  });
  for (const key of ['minimum', 'confidence']) {
    $(`#${key}`).addEventListener('input', event => {
      state[key] = Number(event.target.value);
      $(`#${key}-value`).textContent = key === 'confidence' ? `${state[key]}%` : state[key];
      invalidateScenario();
      scheduleRender();
    });
  }
  $('#partial').addEventListener('change', event => {
    state.partial = event.target.checked;
    invalidateScenario();
    recalculate();
    if (!state.partial) toast(text('completeUnavailable'));
  });
  function setMetric(metric) {
    state.metric = metric;
    invalidateScenario();
    syncControls();
    recalculate();
  }
  $('#gaps-only').addEventListener('change', event => { state.gapsOnly = event.target.checked; recalculate(); });
  $('#metric').addEventListener('change', event => setMetric(event.target.value));
  $$('[data-metric]').forEach(button => button.addEventListener('click', () => setMetric(button.dataset.metric)));
  $('#reset-weights').addEventListener('click', () => {
    state.weights = [...DEFAULT_WEIGHTS];
    renderWeights();
    invalidateScenario();
    recalculate();
  });
  $('#mode-2d').addEventListener('click', () => {
    atlas.set3d(false);
    $('#mode-2d').classList.add('active');
    $('#mode-3d').classList.remove('active');
  });
  $('#mode-3d').addEventListener('click', () => {
    if (atlas.set3d(true)) {
      $('#mode-3d').classList.add('active');
      $('#mode-2d').classList.remove('active');
    }
  });
  $('#reset-map').addEventListener('click', () => atlas.reset());
  $('#toggle-table').addEventListener('click', () => {
    $('#table-panel').hidden = !$('#table-panel').hidden;
    if (!$('#table-panel').hidden) $('#table-panel').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  });
  $$('[data-layer]').forEach(input => input.addEventListener('change', async () => {
    try {
      const ok = await atlas.toggleLayer(input.dataset.layer, input.checked, $('#year').value);
      if (!ok) {
        input.checked = false;
        toast(state.language === 'fr' ? 'Couche disponible dans la carte WebGL.' : 'Layer available in the WebGL map.');
      }
    } catch (error) {
      input.checked = false;
      toast(error.message);
    }
  }));
  $('#year').addEventListener('change', async () => {
    const input = $('[data-layer="hedges"]');
    if (input.checked) {
      try { await atlas.toggleLayer('hedges', true, $('#year').value); }
      catch (error) { toast(error.message); }
    }
  });
  // Sensible default envelope when the constraint type changes (12 sites ≈ 1 200 ha ≈ 10 M€ of farmland).
  const DEFAULT_BUDGET = { sites: 12, hectares: 500, proxy: 5000 };
  $('#constraint').addEventListener('change', () => { $('#budget').value = DEFAULT_BUDGET[$('#constraint').value]; });
  for (const id of ['constraint', 'budget', 'lambda', 'min-area']) {
    $(`#${id}`).addEventListener('input', () => {
      invalidateScenario();
      syncControls();
      recalculate();
    });
  }
  $('#run-scenario').addEventListener('click', runScenario);
  $('#cancel-scenario').addEventListener('click', cancelWorker);
  $('#csv-export').addEventListener('click', () => exportRanking('csv'));
  $('#geo-export').addEventListener('click', () => exportRanking('geojson'));
  $('#export-scenario').addEventListener('click', () => {
    if (state.scenarioStale) return;
    download('renatura-scenario.json', {
      ...state.scenario,
      exported_at: new Date().toISOString(),
      data_build: state.summary.built_at,
      model_version: '1.0.0',
      limitations: state.summary.limits,
    });
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      $('#detail-panel').hidden = true;
      state.selected = null;
    }
  });
  const updateOnline = () => {
    $('#connection-status').innerHTML = `<span></span>${navigator.onLine ? 'Local-first' : state.language === 'fr' ? 'Hors ligne' : 'Offline'}`;
  };
  window.addEventListener('online', updateOnline);
  window.addEventListener('offline', updateOnline);
  updateOnline();
}

function renderRegionalCatalogue() {
  $('#regional-counts').textContent = `${state.summary.declared_layers} couches déclarées · ${num(state.summary.declared_records)} enregistrements sources. Catalogue du projet retrouvé : ${state.catalogue.length} références.`;
  const render = () => { const query=$('#regional-search').value.toLocaleLowerCase(); $('#regional-catalog').innerHTML = state.catalogue.filter(s=>JSON.stringify([s.title,s.categories,s.usage]).toLocaleLowerCase().includes(query)).map(s=>`<article class="regional-source"><strong>${e(s.title)}</strong><small>${e((s.categories||[]).join(' · '))}</small><mark>${e(s.status)}</mark><p>${e(s.usage || s.processing)}</p></article>`).join(''); };
  $('#regional-search').addEventListener('input',render);render();
}

async function initialise() {
  loadURL();
  applyLanguage();
  wireEvents();
  syncControls();
  try {
    const [collection, summary, presets, connectivity, sensitivity, catalogue] = await Promise.all([
      loadCells(), readJSON('summary.json'), readJSON('scenarios.json'),
      readJSON('connectivity.json'), readJSON('sensitivity.json'), readJSON('data_catalog.json'),
    ]);
    Object.assign(state, { collection, summary, presets, connectivity, sensitivity, catalogue });
    try { state.layerScoring = await readJSON('layer_scoring.json'); }
    catch { state.layerScoring = null; } // Older builds without the multilayer scorer simply lack this file.
    const regionalConfig = await readJSON('regional_config.json');
    $('#year').innerHTML = regionalConfig.hedge_years.map(year=>`<option>${e(year)}</option>`).join('');
    $('#year').value = String(regionalConfig.hedge_years.at(-1));
    const observedYears=regionalConfig.hedge_years;
    copy.fr.mapNote=`Maillage ${regionalConfig.hex_area_km2} km² · Indice indicatif, pas un diagnostic écologique`;
    copy.en.mapNote=`${regionalConfig.hex_area_km2} km² grid · Decision support, not an ecological diagnosis`;
    document.querySelector('[data-i18n="mapNote"]').textContent=text('mapNote');
    copy.fr.yearNote=`Change la couche observée, pas les scores ${observedYears.join('–')}.`;
    copy.en.yearNote=`Changes the observed layer, not the ${observedYears.join('–')} scores.`;
    copy.fr.hedgeLength=`Haies mesurées · ${observedYears.at(-1)}`;
    document.querySelector('[data-i18n="yearNote"]').textContent=text('yearNote');
    document.querySelector('[data-i18n="hedgeLength"]').textContent=text('hedgeLength');
    if (!regionalConfig.connectivity_available) {
      $('#lambda').value='0'; $('#lambda').disabled=true;
      $('#metric option[value="betweenness"]').disabled=true;
      document.querySelector('[data-layer="routes"]').disabled=true;
    }

    state.sites = collection.features.map(feature => feature.properties);
    computeProtection();
    applyCommuneNames(collection);
    applyPredictions(collection);
    attachLandPrices();
    const rendered = recalculate();
    renderStatistics();
    renderRegionalCatalogue();
    if (state.summary.regional_readiness) {
      const a=state.summary.regional_readiness;
      $('#regional-counts').textContent += ` Critères complets : ${a.all_four_criteria_cells}/${state.sites.length} mailles. Graphe calculé : ${a.connectivity.cells}/${state.sites.length} mailles ; ${a.connectivity.corridors} corridors.`;
    }
    $('#lambda').dispatchEvent(new Event('input'));
    renderPresets();
    renderDocuments();
    await atlas.initialise(rendered);
    try { await atlas.toggleLayer('boundary', true); }
    catch (error) { toast(error.message); }
    $('#loading').hidden = true;
    if (false && 'serviceWorker' in navigator && window.isSecureContext) {
      navigator.serviceWorker.register('./sw.js').catch(error => console.warn('Offline cache:', error.message));
    }
  } catch (error) {
    $('#loading').innerHTML = `<div><strong>${state.language === 'fr' ? 'Données indisponibles' : 'Data unavailable'}</strong><p>${e(error.message)}</p><p>Exécuter tools/build_normandie.py --renatura-root /chemin/renatura puis servir dist en HTTP.</p></div>`;
    $('#run-scenario').disabled = true;
  }
}

initialise();
