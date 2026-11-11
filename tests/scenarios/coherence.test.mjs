/**
 * Coherence tests for the scenario lab (dist/worker.js + dist/core.js) on the real Normandy data.
 * Run: node tests/scenarios/coherence.test.mjs
 * Each check states a property a sensible answer must have; the script exits 1 if any check fails.
 */
import fs from 'fs';
import zlib from 'zlib';
import path from 'path';
import { fileURLToPath } from 'url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const DATA = path.join(ROOT, 'dist/data/normandie');
let reply;
globalThis.self = { postMessage: m => { reply = m; } };
await import(path.join(ROOT, 'dist/worker.js'));

const fc = JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(DATA, 'cells.geojson.gz'))));
const sites = fc.features.map(f => ({ ...f.properties }));
const buyer = JSON.parse(fs.readFileSync(path.join(DATA, 'buyer_cells.json')));
const price = new Map(buyer.cells.map(c => [c.id, (c.price?.agri || c.price?.rural)?.median]));
for (const s of sites) {  // same rule as regional-app.js attachLandPrices()
  const p = price.get(s.id);
  s.land_eur_ha = Number.isFinite(p) ? p : null;
  s.land_cost_keur = Number.isFinite(p) ? p * s.area_ha / 1000 : null;
}
const paths = JSON.parse(fs.readFileSync(path.join(DATA, 'connectivity.json'))).paths || [];
const byId = new Map(sites.map(s => [s.id, s]));
const WEIGHTS = [0.3, 0.3, 0.15, 0.25];

function solve(mode, budget, { lambda = 0, minArea = 50 } = {}) {
  self.onmessage({ data: { type: 'solve', requestId: 1, payload: { sites, paths, weights: WEIGHTS, partial: true, mode, budget, lambda, minArea } } });
  if (reply.error) throw new Error(reply.error);
  return reply.result;
}

let failed = 0, passed = 0;
function check(name, ok, detail = '') {
  if (ok) passed++; else failed++;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  — ${detail}` : ''}`);
}
const fmt = (v, d = 0) => Number(v).toFixed(d);
const median = a => { const s = [...a].sort((x, y) => x - y); return s[Math.floor(s.length / 2)]; };

const CASES = { sites: [1, 5, 12, 30], hectares: [100, 500, 1500, 3000], proxy: [1000, 5000, 15000, 40000] };
const UNIT = { sites: 'sites', hectares: 'ha', proxy: 'k€' };
const results = {};

for (const lambda of [0, 0.35]) {
  for (const [mode, budgets] of Object.entries(CASES)) {
    let prev = -Infinity;
    for (const budget of budgets) {
      const r = solve(mode, budget, { lambda });
      results[`${mode}|${budget}|${lambda}`] = r;
      const sel = r.selected.map(id => byId.get(id));
      const tag = `[${mode} ${budget} ${UNIT[mode]}, λ=${lambda}]`;
      check(`${tag} respecte l'enveloppe`, r.used <= budget + 1e-6, `${fmt(r.used, 1)} / ${budget}`);
      check(`${tag} aucun site < 50 ha`, sel.every(s => s.area_ha >= 50), `plus petit ${fmt(Math.min(...sel.map(s => s.area_ha)), 1)} ha`);
      check(`${tag} sélection non vide`, sel.length > 0, `${sel.length} sites`);
      check(`${tag} plus d'enveloppe => objectif au moins égal`, r.objective >= prev - 1e-6, `${fmt(prev, 1)} -> ${fmt(r.objective, 1)}`);
      prev = r.objective;
      if (mode === 'sites') check(`${tag} nombre de sites = enveloppe`, sel.length === Math.min(budget, r.eligible), `${sel.length}`);
      if (mode === 'hectares') check(`${tag} enveloppe bien utilisée (>= 90 %)`, r.used >= 0.9 * budget, `${fmt(r.used / budget * 100)} %`);
      if (mode === 'proxy') check(`${tag} toutes les mailles ont un prix connu`, sel.every(s => s.land_cost_keur > 0));
    }
  }
}

// --- cross-mode coherence (λ = 0: pure priority)
const sites5 = new Set(results['sites|5|0'].selected), ha500 = new Set(results['hectares|500|0'].selected);
const overlap = [...sites5].filter(id => ha500.has(id)).length;
check('5 sites et 500 ha choisissent (presque) les mêmes mailles', overlap >= 4, `${overlap}/5 en commun`);

// sites mode, λ = 0 must equal the top-N by value (RP × area/100) among eligible cells
const top = results['sites|12|0'].selected;
const rpOf = s => {  // the value the solver uses, recomputed independently (all four criteria present everywhere)
  const v = WEIGHTS.reduce((t, w, i) => t + w * s['VDPO'[i]], 0) / WEIGHTS.reduce((a, b) => a + b, 0);
  return v * Math.min(s.area_ha, 100) / 100;
};
const ref = sites.filter(s => s.area_ha >= 50 && s.V >= 10).sort((a, b) => rpOf(b) - rpOf(a)).slice(0, 12).map(s => s.id).sort();
check('12 sites (λ=0) = les 12 meilleures mailles calculées indépendamment', JSON.stringify([...top].sort()) === JSON.stringify(ref));

// land budget: at equal money, cheaper land should be favoured and land cost must add up
const land = results['proxy|5000|0'].selected.map(id => byId.get(id));
const regionalMedian = median(sites.map(s => s.land_eur_ha).filter(Number.isFinite));
const landMedian = median(land.map(s => s.land_eur_ha));
check('budget foncier : terres retenues moins chères que la médiane normande', landMedian < regionalMedian, `${fmt(landMedian)} €/ha vs ${fmt(regionalMedian)} €/ha`);
const landTotal = land.reduce((t, s) => t + s.land_cost_keur, 0);
check('budget foncier : somme des coûts = enveloppe utilisée', Math.abs(landTotal - results['proxy|5000|0'].used) < 1e-6, `${fmt(landTotal, 1)} k€`);
const rpLand = median(land.map(s => rpOf(s))), rpAll = median(sites.filter(s => s.area_ha >= 50).map(rpOf));
check('budget foncier : priorité des mailles retenues au-dessus de la médiane', rpLand > rpAll, `RP ${fmt(rpLand, 1)} vs ${fmt(rpAll, 1)}`);

// fragments: even without the minimum-area filter, the area-weighted value must not fill the envelope with slivers
const noMin = solve('hectares', 500, { minArea: 0 }).selected.map(id => byId.get(id));
check('sans filtre de surface, 500 ha ne se remplit pas de fragments', noMin.length <= 6, `${noMin.length} sites, plus petit ${fmt(Math.min(...noMin.map(s => s.area_ha)), 1)} ha`);

// connectivity: corridors exist, and a higher weight must never lower the number of complete corridors
check('des corridors régionaux sont calculés', paths.length > 0, `${paths.length} corridors`);
let prevConn = -Infinity, prevPrio = Infinity;
for (const lambda of [0, 0.35, 1, 2]) {
  const r = solve('sites', 30, { lambda });
  check(`[30 sites, λ=${lambda}] connexions non décroissantes avec le poids`, r.connectivity_total >= prevConn - 1e-6, `${fmt(r.connectivity_total, 1)}`);
  check(`[30 sites, λ=${lambda}] priorité seule non croissante avec le poids`, r.priority_total <= prevPrio + 1e-6, `${fmt(r.priority_total, 1)}`);
  prevConn = r.connectivity_total; prevPrio = r.priority_total;
  if (lambda === 2) check('[30 sites, λ=2] au moins un corridor complet retenu', r.connectivity_total > 0, `${fmt(r.connectivity_total, 1)}`);
}

// browser search vs exact optimum (PuLP / CBC, computed with tools/normandie/regional_model/optimisation.py, min_area 50)
const CBC = [['sites', 30, 1, 2974.0], ['sites', 30, 2, 3146.9], ['hectares', 3000, 1, 2974.0], ['proxy', 15000, 2, 2967.0], ['sites', 60, 2, 5998.5]];
for (const [mode, budget, lambda, optimum] of CBC) {
  const r = solve(mode, budget, { lambda });
  check(`[${mode} ${budget}, λ=${lambda}] navigateur à moins de 1 % de l'optimum exact`, r.objective >= 0.99 * optimum - 1e-6 && r.objective <= optimum + 0.05,
    `${fmt(r.objective, 1)} / optimum ${fmt(optimum, 1)} en ${fmt(r.elapsed_ms / 1000, 1)} s`);
}

// precomputed scenarios (Python / CBC, tools/normandie/complete_region.py) follow the same rules as the browser
const presets = JSON.parse(fs.readFileSync(path.join(DATA, 'scenarios.json')));
check('5 scénarios précalculés', presets.length === 5, `${presets.length}`);
for (const p of presets) {
  const sel = p.selected.map(id => byId.get(id));
  const costOf = s => p.mode === 'sites' ? 1 : p.mode === 'hectares' ? s.area_ha : s.land_cost_keur;
  const used = sel.reduce((t, s) => t + costOf(s), 0);
  check(`[préréglage « ${p.name} »] respecte l'enveloppe`, used <= p.budget + 1e-6, `${fmt(used, 1)} / ${p.budget}`);
  check(`[préréglage « ${p.name} »] aucun site < 50 ha`, sel.every(s => s.area_ha >= 50));
  const browser = solve(p.mode, p.budget, { lambda: p.connectivity_weight });
  check(`[préréglage « ${p.name} »] même valeur que le calcul du navigateur`, Math.abs(browser.objective - p.objective) <= 0.01 * Math.max(1, p.objective),
    `Python ${fmt(p.objective, 1)} / navigateur ${fmt(browser.objective, 1)}`);
}

// minimum area filter really removes cells
check('le filtre de 50 ha exclut des mailles', results['sites|12|0'].eligible < sites.length, `${results['sites|12|0'].eligible}/${sites.length} éligibles`);

console.log(`\n${passed} réussis, ${failed} échoués`);
process.exit(failed ? 1 : 0);
