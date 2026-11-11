import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  scoreSite, rankSites, normaliseWeights, connectionTotal,
  baselineSelection, csvCell, DEFAULT_WEIGHTS, objective,
} from '../../dist/core.js';

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

