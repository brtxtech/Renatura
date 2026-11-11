/** Bounded local computation. No network calls, WebAssembly or backend. */
import {
  rankSites,
  siteCost,
  connectionTotal,
  objective,
  baselineSelection,
  seededRandom,
} from './core.js';

function solve(payload) {
  const { sites, paths, weights, partial, mode, budget, lambda } = payload;
  if (!Number.isFinite(budget) || budget < 0 || !Number.isFinite(lambda) || lambda < 0) {
    throw new Error('Invalid budget or connectivity weight.');
  }
  const start = performance.now();
  const ranked = rankSites(sites, weights, partial);
  if (!ranked.length) throw new Error('No eligible sites with these data and filters.');
  if (ranked.some(site => !Number.isFinite(siteCost(site, mode)) || siteCost(site, mode) <= 0)) {
    throw new Error('Missing or nonpositive site costs.');
  }
  const lookup = new Map(ranked.map(site => [site.id, site]));
  const usablePaths = paths.filter(path => path.sites.every(id => lookup.has(id)));
  const baseline = baselineSelection(ranked, mode, budget);
  let best = new Set(baseline);
  let bestValue = objective(best, lookup, usablePaths, lambda);
  const baselineValue = bestValue;
  const costOf = ids => [...ids].reduce((sum, id) => sum + siteCost(lookup.get(id), mode), 0);
  const valueOf = ids => objective(ids, lookup, usablePaths, lambda);
  const totalConnections = lambda * usablePaths.reduce((sum, path) => sum + path.gain, 0);

  // Bundle-aware greedy warm start: entire routes compete with individual cells.
  let greedy = new Set();
  let used = 0;
  while (performance.now() - start < 650) {
    let winner = null;
    let winnerRatio = -Infinity;
    const currentValue = valueOf(greedy);
    const options = [
      ...ranked.filter(site => !greedy.has(site.id)).map(site => [site.id]),
      ...usablePaths.map(path => path.sites.filter(id => !greedy.has(id))),
    ];
    for (const bundle of options) {
      if (!bundle.length) continue;
      const extra = costOf(bundle);
      if (used + extra > budget + 1e-8) continue;
      const candidate = new Set([...greedy, ...bundle]);
      const ratio = (valueOf(candidate) - currentValue) / extra;
      if (ratio > winnerRatio) {
        winner = bundle;
        winnerRatio = ratio;
      }
    }
    if (!winner) break;
    used += costOf(winner);
    for (const id of winner) greedy.add(id);
  }
  if (valueOf(greedy) > bestValue) {
    best = new Set(greedy);
    bestValue = valueOf(greedy);
  }

  // Fractional relaxation bounds additive priority; all routes bound synergy.
  const ordered = [...ranked].sort((a, b) =>
    b.score / siteCost(b, mode) - a.score / siteCost(a, mode));
  function bound(index, remaining, accumulated) {
    let result = accumulated + totalConnections;
    for (let i = index; i < ordered.length; i++) {
      const item = ordered[i];
      const cost = siteCost(item, mode);
      const take = Math.min(1, remaining / cost);
      result += take * item.score;
      remaining -= take * cost;
      if (remaining <= 1e-10) break;
    }
    return result;
  }
  const universalBound = bound(0, budget, 0);
  let proven = mode === 'sites' && lambda === 0;
  let nodes = 0;
  if (proven) {
    best = new Set(baseline);
    bestValue = baselineValue;
  } else {
    const stack = [{ index: 0, used: 0, priority: 0, chosen: [] }];
    while (stack.length && performance.now() - start < 3000 && nodes < 200000) {
      const state = stack.pop();
      nodes++;
      if (bound(state.index, budget - state.used, state.priority) <= bestValue + 1e-8) continue;
      if (state.index === ordered.length) {
        const value = valueOf(state.chosen);
        if (value > bestValue + 1e-8) {
          best = new Set(state.chosen);
          bestValue = value;
        }
        continue;
      }
      const site = ordered[state.index];
      const next = state.index + 1;
      stack.push({ ...state, index: next });
      const cost = siteCost(site, mode);
      if (state.used + cost <= budget + 1e-8) {
        stack.push({ index: next, used: state.used + cost,
          priority: state.priority + site.score, chosen: [...state.chosen, site.id] });
      }
    }
    proven = stack.length === 0;
  }
  const selected = [...best].sort();
  const upper = proven ? bestValue : Math.max(bestValue, universalBound);
  return {
    id: 'custom',
    name: 'Browser scenario',
    status: proven ? 'OPTIMAL' : 'FEASIBLE',
    selected,
    baseline,
    mode,
    budget,
    used: costOf(selected),
    weights,
    connectivity_weight: lambda,
    allow_partial: partial,
    objective: bestValue,
    baseline_objective: baselineValue,
    priority_total: selected.reduce((sum, id) => sum + lookup.get(id).score, 0),
    connectivity_total: connectionTotal(best, usablePaths),
    baseline_connectivity: connectionTotal(baseline, usablePaths),
    gain_percent: baselineValue > 0 ? 100 * (bestValue / baselineValue - 1) : null,
    area_ha: selected.reduce((sum, id) => sum + lookup.get(id).area_ha, 0),
    proxy_cost: selected.reduce((sum, id) => sum + lookup.get(id).proxy_cost, 0),
    upper_bound: upper,
    bound_kind: proven ? 'exact' : 'fractional priority plus all modelled connections',
    gap_percent: 100 * (upper - bestValue) / Math.max(Math.abs(bestValue), 1),
    elapsed_ms: performance.now() - start,
    nodes,
    solver: 'Browser branch-and-bound with bundle greedy warm start; 3-second / 200k-node cap',
  };
}

function sensitivity(payload) {
  const { sites, weights, partial } = payload;
  const random = seededRandom(42);
  const baseline = rankSites(sites, weights, partial);
  if (!baseline.length) throw new Error('No eligible sites.');
  const size = Math.min(20, baseline.length);
  const initial = new Set(baseline.slice(0, size).map(s => s.id));
  const samples = new Map(baseline.map(site => [site.id, []]));
  const counts = new Map(baseline.map(site => [site.id, 0]));
  let overlap = 0;
  const runs = 200;
  for (let i = 0; i < runs; i++) {
    const varied = weights.map(weight => weight * (0.8 + random() * 0.4));
    const ranked = rankSites(sites, varied, partial);
    const top = new Set(ranked.slice(0, size).map(s => s.id));
    const intersection = [...initial].filter(id => top.has(id)).length;
    overlap += intersection / (size * 2 - intersection);
    ranked.forEach((site, index) => {
      samples.get(site.id).push(index + 1);
      if (top.has(site.id)) counts.set(site.id, counts.get(site.id) + 1);
    });
  }
  return {
    runs,
    seed: 42,
    variation: .2,
    weights,
    allow_partial: partial,
    mean_top20_jaccard: overlap / runs,
    mean_rank_correlation: null,
    sites: baseline.map((site, index) => {
      const ranks = samples.get(site.id).sort((a, b) => a - b);
      return {
        id: site.id,
        baseline_rank: index + 1,
        top20_frequency: counts.get(site.id) / runs,
        median_rank: ranks[Math.floor(runs / 2)],
        rank_p05: ranks[Math.floor(runs * .05)],
        rank_p95: ranks[Math.floor(runs * .95)],
      };
    }),
  };
}

self.onmessage = event => {
  const { type, payload, requestId } = event.data;
  try {
    const result = type === 'solve' ? solve(payload) : sensitivity(payload);
    self.postMessage({ requestId, type, result });
  } catch (error) {
    self.postMessage({ requestId, error: error.message });
  }
};
