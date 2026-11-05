import {
  KEYS, DEFAULT_WEIGHTS, normaliseWeights, scoreSite, rankSites,
  formatNumber, escapeHTML as e, csvCell, sameWeights,
} from './core.js';
import { copy } from './i18n.js';
import { AtlasMap } from './map.js';
import { methodology, sourcesPage } from './documents.js';

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
  const response = await fetch(`data/${name}`);
  if (!response.ok) throw new Error(`Data file ${name}: HTTP ${response.status}`);
  return response.json();
}

function loadURL() {
  const params = new URLSearchParams(location.search);
  if (params.get('lang') === 'en') state.language = 'en';
  const weights = params.get('w')?.split(',').map(Number);
  if (weights) {
    try { state.weights = normaliseWeights(weights); } catch { /* Keep documented defaults. */ }
  }
  const metric = params.get('metric');
  if (['RP', 'PP', 'V', 'D', 'P', 'O', 'betweenness'].includes(metric)) state.metric = metric;
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
    if (key === 'headline') element.innerHTML = text(key);
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
}

function metricValue(site) {
  if (state.metric === 'RP') return scoreSite(site, state.weights, state.partial).score;
  if (state.metric === 'PP') return null;
  if (state.metric === 'betweenness') return site.betweenness * 100;
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
      && (state.minimum === 0 || (Number.isFinite(value) && value >= state.minimum));
  });
  state.ranked = rankSites(state.filtered, state.weights, state.partial);
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
  $('#legend-title').textContent = state.metric === 'RP' ? text('score') : state.metric;
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
  $('#ranking-body').innerHTML = state.ranked.slice(0, 20).map((site, index) => `
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

function showDetail(id, fly = true) {
  const feature = state.collection.features.find(feature => feature.properties.id === id);
  if (!feature) return;
  state.selected = id;
  const site = feature.properties;
  const score = scoreSite(site, state.weights, state.partial);
  const panel = $('#detail-panel');
  const en = state.language === 'en';
  panel.innerHTML = `
    <button class="close-detail" aria-label="${en ? 'Close details' : 'Fermer les détails'}">×</button>
    <div class="eyebrow">${e(site.id)}</div>
    <h3>${e(site.commune)}</h3>
    <p class="micro">${num(site.area_ha, 1)} ha · ${num(site.coverage)}% ${text('coverage').toLowerCase()}</p>
    <div class="detail-score">${num(score.score, 1)} <small>/100 · ${text('score')}</small></div>
    ${KEYS.map((key, i) => `
      <div class="breakdown-row">
        <div><span>${key} · ${e(text('breakdown')[i])}</span><strong>${num(site[key])}</strong></div>
        <div class="breakdown-track"><i style="width:${Number.isFinite(site[key]) ? site[key] : 0}%"></i></div>
      </div>`).join('')}
    <p class="micro">${en ? 'This cell combines observed woody structure with net hedgerow decline. Pressure and land availability remain unknown.' : 'Cette cellule combine une structure boisée observée et un recul net des haies. La pression et la disponibilité foncière restent inconnues.'}</p>
    <dl class="detail-raw">
      <dt>${en ? 'Hedgerows' : 'Haies'} 1947</dt><dd>${num(site.hedge_1947_m)} m</dd>
      <dt>${en ? 'Hedgerows' : 'Haies'} 2010</dt><dd>${num(site.hedge_2010_m)} m</dd>
      <dt>${en ? 'Hedgerows' : 'Haies'} 2016</dt><dd>${num(site.hedge_2016_m)} m</dd>
      <dt>${en ? 'Woodland' : 'Bois'} 2016</dt><dd>${num(site.woodland_ha, 1)} ha</dd>
      <dt>${en ? 'Betweenness' : 'Intermédiarité'}</dt><dd>${num(site.betweenness, 4)}</dd>
    </dl>
    <p class="micro">DREAL Normandie · 1947 / 2010 / 2016 · Licence Ouverte 2.0</p>`;
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
      <span><strong>${e(state.language === 'fr' ? preset.name : ['Focused intervention', 'Balanced network', 'Territorial ambition', '500 ha envelope', '1,000 proxy units'][index])}</strong>
      <small>${num(preset.budget)} ${preset.mode === 'sites' ? 'sites' : preset.mode === 'hectares' ? 'ha' : 'proxy'} · ${preset.status === 'OPTIMAL' ? 'ILP ✓' : 'ILP'}</small></span>
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
  $('#budget-unit').textContent = $('#constraint').value === 'sites' ? 'sites' : $('#constraint').value === 'hectares' ? 'ha' : 'proxy';
  $$('[data-metric]').forEach(button => button.classList.toggle('active', button.dataset.metric === state.metric));
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
    <p class="micro">${text('upper')}: ${num(result.upper_bound, 1)} · ${text('gap')}: ${num(result.gap_percent, 1)}%</p>
    <div class="coverage-note"><span>!</span><p>${text('partialNotice')}</p></div>`;
}

function startWorker() {
  if (state.worker) return;
  state.worker = new Worker(new URL('./worker.js', import.meta.url), { type: 'module' });
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
  const top = state.ranked.slice(0, 20);
  if (type === 'csv') {
    const keys = ['id', 'commune', 'score', 'V', 'D', 'P', 'O', 'coverage', 'area_ha', 'partial'];
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
    + (state.language === 'fr' ? 'Analyse sur tout le pilote, indépendamment des filtres.' : 'Analysis covers the entire pilot, independently of filters.');
}

function renderDocuments() {
  $('#method-page').innerHTML = methodology(state.language, state.sensitivity, state.sites, state.summary);
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
  $('#workspace').hidden = ['method', 'sources'].includes(page);
  $('#method-page').hidden = page !== 'method';
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
  for (const id of ['constraint', 'budget', 'lambda']) {
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

async function initialise() {
  loadURL();
  applyLanguage();
  wireEvents();
  syncControls();
  try {
    const [collection, summary, presets, connectivity, sensitivity, catalogue] = await Promise.all([
      readJSON('cells.geojson'), readJSON('summary.json'), readJSON('scenarios.json'),
      readJSON('connectivity.json'), readJSON('sensitivity.json'), readJSON('data_catalog.json'),
    ]);
    Object.assign(state, { collection, summary, presets, connectivity, sensitivity, catalogue });
    state.sites = collection.features.map(feature => feature.properties);
    const rendered = recalculate();
    renderStatistics();
    renderPresets();
    renderDocuments();
    await atlas.initialise(rendered);
    try { await atlas.toggleLayer('boundary', true); }
    catch (error) { toast(error.message); }
    $('#loading').hidden = true;
    if ('serviceWorker' in navigator && window.isSecureContext) {
      navigator.serviceWorker.register('./sw.js').catch(error => console.warn('Offline cache:', error.message));
    }
  } catch (error) {
    $('#loading').innerHTML = `<div><strong>${state.language === 'fr' ? 'Données indisponibles' : 'Data unavailable'}</strong><p>${e(error.message)}</p><p>Run ./run.sh and serve the dist directory over HTTP(S).</p></div>`;
    $('#run-scenario').disabled = true;
  }
}

initialise();
