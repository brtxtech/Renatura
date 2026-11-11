/** Pure numerical functions used by the interface, worker and Node tests. */
export const KEYS = ['V', 'D', 'P', 'O'];
export const DEFAULT_WEIGHTS = [0.30, 0.30, 0.15, 0.25];

export function normaliseWeights(values) {
  if (values.length !== 4 || values.some(v => !Number.isFinite(v) || v < 0)) {
    throw new Error('Four finite nonnegative weights are required.');
  }
  const sum = values.reduce((a, b) => a + b, 0);
  if (sum <= 0) throw new Error('At least one weight must be positive.');
  return values.map(v => v / sum);
}

export function scoreSite(site, weights, partial = false, minimumV = 10) {
  const normal = normaliseWeights(weights);
  const available = KEYS.map(key => Number.isFinite(site[key]));
  const coverage = available.filter(Boolean).length * 25;
  const weightedCoverage = normal.reduce((sum, weight, i) => sum + (available[i] ? weight : 0), 0);
  const complete = available.every((yes, i) => yes || normal[i] === 0);
  // minimumV: pilot method keeps V >= 10 (no structure left to restore); the regional explorer passes 0
  const eligible = Number.isFinite(site.V) && site.V >= minimumV;
  if (!eligible || weightedCoverage === 0 || (!partial && !complete)) {
    return { score: null, coverage, partial: !complete, eligible: false };
  }
  const sum = KEYS.reduce((value, key, i) => value + (available[i] ? site[key] * normal[i] : 0), 0);
  return { score: sum / weightedCoverage, coverage, partial: !complete, eligible: true };
}

export function rankSites(sites, weights, partial, minimumV = 10) {
  return sites.map(site => ({ ...site, ...scoreSite(site, weights, partial, minimumV) }))
    .filter(site => Number.isFinite(site.score))
    .sort((a, b) => b.score - a.score || a.id.localeCompare(b.id));
}

export function siteCost(site, mode) {
  if (mode === 'sites') return 1;
  if (mode === 'hectares') return site.area_ha;
  // Regional explorer: land cost in k€ (DVF median €/ha × area, attached by regional-app.js; null = no price).
  // Pilot explorer (no land_cost_keur field): its own surface proxy.
  if (mode === 'proxy') return 'land_cost_keur' in site ? site.land_cost_keur : site.proxy_cost;
  throw new Error('Unknown constraint.');
}

export function connectionTotal(selected, paths) {
  const chosen = selected instanceof Set ? selected : new Set(selected);
  return paths.reduce((sum, path) => sum + (path.sites.every(id => chosen.has(id)) ? path.gain : 0), 0);
}

export function objective(selected, lookup, paths, lambda) {
  const chosen = selected instanceof Set ? selected : new Set(selected);
  let score = 0;
  for (const id of chosen) score += lookup.get(id).score;
  return score + lambda * connectionTotal(chosen, paths);
}

export function baselineSelection(ranked, mode, budget) {
  let used = 0;
  const selected = [];
  for (const site of ranked) {
    const cost = siteCost(site, mode);
    if (used + cost <= budget + 1e-8) {
      selected.push(site.id);
      used += cost;
    }
  }
  return selected;
}

export function formatNumber(value, digits = 0, language = 'fr') {
  if (!Number.isFinite(value)) return '—';
  return new Intl.NumberFormat(language === 'fr' ? 'fr-FR' : 'en-GB', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

export function escapeHTML(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
}

export function csvCell(value) {
  let text = String(value ?? '');
  // Neutralise spreadsheet formula injection in externally sourced names.
  if (/^[=+@\-]/.test(text)) text = `'${text}`;
  return `"${text.replace(/"/g, '""')}"`;
}

export function sameWeights(left, right) {
  return normaliseWeights(left).every((v, i) => Math.abs(v - normaliseWeights(right)[i]) < 1e-8);
}

export function seededRandom(seed) {
  let value = seed >>> 0;
  return () => {
    value += 0x6D2B79F5;
    let t = value;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
