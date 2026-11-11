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
  sources: new Map(),
  atlasZones: null,
  analysisMode: false,
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
  const response = await fetch(new URL(`../data/${name}`, window.location.href));
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
    renderRegionalCatalogue();
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
  $('#regional-coverage').textContent = `${num(state.summary.coverage_min / 25)}–${num(state.summary.coverage_max / 25)} / 4`;
}

function metricValue(site) {
  if (state.metric === 'RP') return scoreSite(site, state.weights, state.partial).score;
  if (state.metric === 'PP') return null;
  if (state.metric === 'betweenness') return Number.isFinite(site.betweenness) ? site.betweenness * 100 : null;
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
        return {
          ...feature, properties: {
            ...feature.properties,
            display: Number.isFinite(display) ? display : 0,
            missing: !Number.isFinite(display), selected: selected.has(feature.properties.id)
          }
        };
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
        <div class="breakdown-track ${Number.isFinite(site[key]) ? '' : 'is-missing'}" title="${Number.isFinite(site[key]) ? '' : (en ? 'No data for this cell' : 'Donnée absente pour cette maille')}">${Number.isFinite(site[key]) ? `<i style="width:${site[key]}%"></i>` : ''}</div>
      </div>`).join('')}
    <p class="micro">${en ? 'Displayed criteria use observations covering this cell. Inspect provenance and missing criteria below.' : 'Les critères affichés sont calculés uniquement à partir des observations couvrant cette maille. Consulter les sources et les critères manquants ci-dessous.'}</p>
    <dl class="detail-raw">
      <dt>${en ? 'Hedgerows' : 'Haies'} 1947</dt><dd>${num(site.hedge_1947_m)} m</dd>
      <dt>${en ? 'Hedgerows' : 'Haies'} ${e(site.observation_years?.before || 2010)}</dt><dd>${num(site.hedge_2010_m)} m</dd>
      <dt>${en ? 'Hedgerows' : 'Haies'} ${e(site.observation_years?.after || 2016)}</dt><dd>${num(site.hedge_2016_m)} m</dd>
      <dt>${en ? 'Woodland' : 'Bois'} ${e(site.observation_years?.after || 2016)}</dt><dd>${num(site.woodland_ha, 1)} ha</dd>
      <dt>${en ? 'Betweenness' : 'Intermédiarité'}</dt><dd>${num(site.betweenness, 4)}</dd>
    </dl>
    <p class="micro">DREAL Normandie · 1947 / 2010 / 2016 · Licence Ouverte 2.0</p>`;
  const evidence = site.evidence || {};
  panel.insertAdjacentHTML('beforeend', `<div class="regional-provenance"><h4>Sources réellement utilisées</h4>${KEYS.map(key => `<p><b>${key}</b> : ${Number.isFinite(site[key]) ? num(site[key], 1) : 'absent'}</p><ul>${(evidence[key] || []).map(row => `<li>${e(state.catalogue.find(s => s.id === row.sourceId)?.title || row.sourceId)} · ${e(row.year)} · ${e(row.metric)} : ${num(row.value, 2)} ${e(row.unit)}</li>`).join('') || '<li>Pas de mesure validée couvrant cette maille.</li>'}</ul>`).join('')}<p class="micro">Référence : ${e(site.normalization_reference || state.summary.site)}. Les valeurs régionales ne sont pas extrapolées depuis Bocages.</p></div>`);
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
    + (state.language === 'fr' ? 'Analyse sur toutes les mailles régionales chargées, indépendamment des filtres.' : 'Analysis covers all loaded regional cells, independently of filters.');
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
      toggleAtlasAnalysisMode(false);
    }
  });
  const updateOnline = () => {
    $('#connection-status').innerHTML = `<span></span>${navigator.onLine ? 'Local-first' : state.language === 'fr' ? 'Hors ligne' : 'Offline'}`;
  };
  window.addEventListener('online', updateOnline);
  window.addEventListener('offline', updateOnline);
  updateOnline();
  $('#analyse-cell').addEventListener('click', () => {
    toggleAtlasAnalysisMode(!state.analysisMode);
  });
  $('#analyse-cell').addEventListener('mouseenter', () => {
    if (atlas.map && atlas.map.getCanvas) atlas.map.getCanvas().style.cursor = 'crosshair';
  });
  $('#analyse-cell').addEventListener('mouseleave', () => {
    if (!state.analysisMode && atlas.map && atlas.map.getCanvas) atlas.map.getCanvas().style.cursor = '';
  });
  const handleMapClick = event => {
    if (state.analysisMode) {
      analyseCellAt(event.lngLat.lng, event.lngLat.lat);
      toggleAtlasAnalysisMode(false);
      return;
    }
    const ids = [...state.sources.values()].flat().flatMap(id => [id + '-fill', id + '-line', id + '-point']).filter(id => atlas.map?.getLayer(id));
    const fs = ids.length ? atlas.map.queryRenderedFeatures(event.point, { layers: ids }) : [];
    if (fs.length) {
      if (fs[0].properties._aggregation) analyseCellAt(event.lngLat.lng, event.lngLat.lat);
      else showDetail(fs[0].properties.id);
    }
  };
  atlas.map?.on('click', handleMapClick);
}

function renderRegionalCatalogue() {
  $('#regional-counts').textContent = `${state.summary.declared_layers} couches déclarées · ${num(state.summary.declared_records)} enregistrements sources. Catalogue du projet retrouvé : ${state.catalogue.length} références.`;
  const render = () => { const query = $('#regional-search').value.toLocaleLowerCase(); $('#regional-catalog').innerHTML = state.catalogue.filter(s => JSON.stringify([s.title, s.categories, s.usage]).toLocaleLowerCase().includes(query)).map(s => `<article class="regional-source"><strong>${e(s.title)}</strong><small>${e((s.categories || []).join(' · '))}</small><mark>${e(s.status)}</mark><p>${e(s.usage || s.processing)}</p></article>`).join(''); };
  $('#regional-search').addEventListener('input', render); render();
}

const atlasZoneSources = new Map();

async function fetchAtlasZone(zoneId) {
  const url = `../data/atlas/zones/${zoneId}.json`;
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Diagnostic de maille indisponible : ${zoneId}`);
  return response.json();
}

async function loadAtlasZones() {
  if (state.atlasZones) return state.atlasZones;
  const response = await fetch('../data/atlas/zones.geojson');
  if (!response.ok) throw new Error('Grille atlas absente : zones.geojson');
  state.atlasZones = await response.json();
  return state.atlasZones;
}

function renderAtlasZoneDetail(zone, results) {
  const panel = $('#detail-panel');
  const en = state.language === 'en';
  const count = results?.layers?.length || 0;
  const themes = new Set((results?.layers || []).flatMap(item => {
    const layer = state.catalogue.find(source => source.id === item.id);
    return layer?.categories || [];
  }));
  const label = (value, fallback) => (Number.isFinite(value) ? value : fallback);

  panel.innerHTML = `
    <button class="close-detail" aria-label="${en ? 'Close details' : 'Fermer les détails'}">×</button>
    <div class="eyebrow">${en ? 'TERRITORIAL CONTEXT' : 'CONTEXTE TERRITORIAL'} · ${e(zone.properties.id)}</div>
    <h3>${en ? 'What do we know in this cell?' : 'Que sait-on de cette maille ?'}</h3>
    <p class="micro">${en ? '5 × 5 km cell — Normandy boundary' : 'Maille de 5 × 5 km — limité au contour normand'} · ${num(zone.properties.area_ha || 0, 1)} ha</p>
    <div class="detail-score" style="font-size:1.15rem; line-height:1.4;">${count} <small>${en ? 'intersected layers' : 'couches intersectées'}</small></div>
    <div class="detail-score" style="font-size:1.15rem; line-height:1.4;">${themes.size} <small>${en ? 'themes represented' : 'thèmes représentés'}</small></div>
    <p class="micro">${en
      ? 'These intersections are computed on the working geometries before the display simplification. Missing information does not prove absence of a topic.'
      : 'Les intersections sont calculées sur les géométries de travail avant la simplification d’affichage. Une absence de donnée ne prouve pas l’absence d’un enjeu.'}
    </p>
    <div class="regional-provenance">
      <h4>${en ? 'Layers with direct evidence in this cell' : 'Couches avec éléments observés dans cette maille'}</h4>
      ${(results?.layers || []).slice().sort((a, b) => (b.count || 0) - (a.count || 0)).map(item => {
        const layer = state.catalogue.find(source => source.id === item.id);
        const status = layer?.status || 'UNKNOWN';
        return `
          <button class="result-row" data-context-layer="${e(item.id)}">
            <b>${num(item.count || 0, 0)}</b>${e(layer?.title || layer?.name || item.id)}<br>
            <span class="badge ${status === 'PARTIAL' ? 'partial' : ''}">${e(status === 'PARTIAL' ? (en ? 'Partial' : 'Partiel') : (status === 'AVAILABLE' ? (en ? 'Available' : 'Disponible') : status))}</span>
          </button>`;
      }).join('') || `<p class="micro">${en ? 'No intersected object in the processed layers.' : 'Aucun objet intersecté dans les couches traitées.'}</p>`}
    </div>
    <button id="export-zone" class="action">${en ? 'Export this diagnosis · GeoJSON' : 'Exporter ce diagnostic · GeoJSON'}</button>
    <p class="micro">${en ? 'This diagnosis is contextual only; it does not compute or validate a restoration score.' : 'Ce diagnostic est purement contextuel ; il ne calcule ni ne valide un score de restauration.'}</p>
  `;

  const closeButton = panel.querySelector('.close-detail');
  closeButton.addEventListener('click', () => {
    panel.hidden = true;
    state.selected = null;
    if (atlas.map && atlas.map.getSource) {
      try { atlas.map.getSource('analysis-zone')?.setData({ type: 'FeatureCollection', features: [] }); } catch { }
    }
  });

  panel.querySelectorAll('[data-context-layer]').forEach(button => {
    button.addEventListener('click', () => {
      const source = state.catalogue.find(item => item.id === button.dataset.contextLayer);
      if (!source) return;
      const detailHtml = `
        <div class="eyebrow">${en ? 'SOURCE' : 'SOURCE'}</div>
        <h3>${e(source.title || source.name || source.id)}</h3>
        <p class="micro">${e((source.categories || []).join(' · ') || source.status || '')}</p>
        <dl class="detail-raw">
          <dt>${en ? 'Producer' : 'Producteur'}</dt><dd>${e(source.producer || '—')}</dd>
          <dt>${en ? 'Status' : 'Statut'}</dt><dd>${e(source.status || '—')}</dd>
          <dt>${en ? 'Processing' : 'Traitement'}</dt><dd>${e(source.processing || '—')}</dd>
          <dt>${en ? 'URL' : 'URL'}</dt><dd>${source.url ? `<a href="${e(source.url)}" target="_blank" rel="noopener">${e(source.url)}</a>` : '—'}</dd>
        </dl>
      `;
      $('#detail-panel').insertAdjacentHTML('beforeend', `<div class="regional-provenance"><h4>${en ? 'Provenance' : 'Provenance'}</h4>${detailHtml}</div>`);
    });
  });

  const exportButton = panel.querySelector('#export-zone');
  exportButton?.addEventListener('click', () => {
    const payload = {
      type: 'FeatureCollection',
      features: [{
        type: 'Feature',
        geometry: zone.geometry,
        properties: {
          zone_id: zone.properties.id,
          area_ha: zone.properties.area_ha,
          note: en ? 'Intersections observed; no automatic score or proof of absence.' : 'Intersections observées, sans score automatique ni preuve d’absence.',
          analysis: results,
        },
      }],
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/geo+json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `Renatura_${zone.properties.id}.geojson`;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });

  panel.hidden = false;
}

async function analyseCellAt(lng, lat) {
  try {
    const zones = await loadAtlasZones();
    const zone = zones.features.find(feature => {
      const p = feature.geometry;
      if (!p || !(p.type === 'Polygon' || p.type === 'MultiPolygon')) return false;
      const x = lng;
      const y = lat;
      const pointInRing = ring => {
        let inside = false;
        for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
          const xi = ring[i][0], yi = ring[i][1];
          const xj = ring[j][0], yj = ring[j][1];
          const intersect = ((yi > y) !== (yj > y)) && (x < ((xj - xi) * (y - yi)) / (yj - yi) + xi);
          if (intersect) inside = !inside;
        }
        return inside;
      };
      if (p.type === 'Polygon') return p.coordinates.some(ring => pointInRing(ring));
      return p.coordinates.some(poly => poly.some(ring => pointInRing(ring)));
    });

    if (!zone) {
      toast(state.language === 'fr' ? 'Aucune maille Normandie à cet endroit.' : 'No Normandy cell at this location.');
      return;
    }

    const results = await fetchAtlasZone(zone.properties.id);
    if (atlas.map && atlas.map.getSource) {
      atlas.map.getSource('analysis-zone')?.setData({ type: 'FeatureCollection', features: [zone] });
    }
    renderAtlasZoneDetail(zone, results);
  } catch (error) {
    toast(error.message || 'Analyse de maille indisponible');
  }
}

function toggleAtlasAnalysisMode(enable) {
  state.analysisMode = enable;
  const button = $('#analyse-cell');
  if (button) button.classList.toggle('active', enable);
  if (atlas.map && atlas.map.getCanvas) {
    atlas.map.getCanvas().style.cursor = enable ? 'crosshair' : '';
  }
  const hint = document.getElementById('analysis-hint');
  if (hint) hint.hidden = !enable;
}
