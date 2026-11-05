import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  scoreSite, rankSites, normaliseWeights, connectionTotal,
  baselineSelection, csvCell, DEFAULT_WEIGHTS, objective,
} from '../dist/core.js';

const fixture = (id, value, area = 1) => ({ id, V: value, D: value, P: value, O: value, area_ha: area, proxy_cost: area });

test('missing criterion does not turn into zero', () => {
  const row = { ...fixture('a', 50), P: null };
  assert.equal(scoreSite(row, DEFAULT_WEIGHTS).score, null);
  assert.equal(scoreSite(row, DEFAULT_WEIGHTS, true).score, 50);
  assert.equal(scoreSite(row, DEFAULT_WEIGHTS, true).coverage, 75);
});

test('all-zero weights are invalid', () => {
  assert.throws(() => normaliseWeights([0, 0, 0, 0]));
});

test('low ecological stake is excluded', () => {
  assert.equal(scoreSite(fixture('a', 8), DEFAULT_WEIGHTS).eligible, false);
});

test('route gain requires every cell', () => {
  const routes = [{ sites: ['a', 'b'], gain: 100 }];
  assert.equal(connectionTotal(['a'], routes), 0);
  assert.equal(connectionTotal(['a', 'b'], routes), 100);
});

test('naive baseline respects hectares while skipping unaffordable sites', () => {
  const rows = rankSites([fixture('a', 90, 10), fixture('b', 80, 2)], DEFAULT_WEIGHTS, false);
  assert.deepEqual(baselineSelection(rows, 'hectares', 3), ['b']);
});

test('CSV exports neutralise formulas and quote values', () => {
  assert.equal(csvCell('=1+1'), '"\'=1+1"');
  assert.equal(csvCell('a"b'), '"a""b"');
});

test('real-data Python and JavaScript objectives agree', () => {
  const cells = JSON.parse(fs.readFileSync(new URL('../dist/data/cells.geojson', import.meta.url))).features.map(f => f.properties);
  const scenarios = JSON.parse(fs.readFileSync(new URL('../dist/data/scenarios.json', import.meta.url)));
  const paths = JSON.parse(fs.readFileSync(new URL('../dist/data/connectivity.json', import.meta.url))).paths;
  for (const result of scenarios) {
    const lookup = new Map(rankSites(cells, result.weights, true).map(s => [s.id, s]));
    assert.ok(Math.abs(objective(result.selected, lookup, paths, result.connectivity_weight) - result.objective) < 1e-6);
  }
});

test('browser worker solves a small connectivity problem exactly', async () => {
  let response;
  globalThis.self = { postMessage: value => { response = value; } };
  await import('../dist/worker.js');
  self.onmessage({ data: { requestId: 1, type: 'solve', payload: {
    sites: [fixture('a', 90), fixture('b', 70), fixture('c', 65)],
    paths: [{ id: 'route', sites: ['b', 'c'], gain: 100 }],
    weights: DEFAULT_WEIGHTS, partial: false, mode: 'sites', budget: 2, lambda: 1,
  } } });
  assert.equal(response.error, undefined);
  assert.equal(response.result.status, 'OPTIMAL');
  assert.deepEqual(response.result.selected, ['b', 'c']);
  assert.equal(response.result.objective, 235);
});

test('browser worker real-data result is feasible and beats its baseline', async () => {
  let response;
  globalThis.self.postMessage = value => { response = value; };
  const sites = JSON.parse(fs.readFileSync(new URL('../dist/data/cells.geojson', import.meta.url))).features.map(f => f.properties);
  const paths = JSON.parse(fs.readFileSync(new URL('../dist/data/connectivity.json', import.meta.url))).paths;
  self.onmessage({ data: { requestId: 2, type: 'solve', payload: {
    sites, paths, weights: DEFAULT_WEIGHTS, partial: true, mode: 'hectares', budget: 500, lambda: .35,
  } } });
  assert.equal(response.error, undefined);
  assert.ok(response.result.used <= 500 + 1e-8);
  assert.ok(response.result.objective >= response.result.baseline_objective - 1e-8);
  assert.ok(response.result.upper_bound >= response.result.objective - 1e-8);
});

test('browser sensitivity returns 200 bounded frequencies', async () => {
  let response;
  globalThis.self.postMessage = value => { response = value; };
  self.onmessage({ data: { requestId: 3, type: 'sensitivity', payload: {
    sites: Array.from({ length: 25 }, (_, i) => fixture(String(i), 20 + i)),
    weights: DEFAULT_WEIGHTS, partial: false,
  } } });
  assert.equal(response.result.runs, 200);
  assert.ok(response.result.sites.every(s => s.top20_frequency >= 0 && s.top20_frequency <= 1));
});
