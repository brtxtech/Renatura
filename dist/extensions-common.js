/* Shared helpers for the extension pages. */
export const $ = (s, el = document) => el.querySelector(s);
export const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
export const fmt = (v, d = 0) => Number.isFinite(v) ? new Intl.NumberFormat('fr-FR', { maximumFractionDigits: d, minimumFractionDigits: d }).format(v) : '—';

/** Load JSON, preferring the .gz copy when the browser can unzip it and the copy is not older. */
export async function loadJSON(path) {
  try {
    if (typeof DecompressionStream === 'undefined') throw new Error('no gzip support');
    const [plain, packed] = await Promise.all([fetch(path, { method: 'HEAD', cache: 'no-store' }), fetch(`${path}.gz`, { method: 'HEAD', cache: 'no-store' })]);
    const tp = Date.parse(plain.headers.get('last-modified') || ''), tg = Date.parse(packed.headers.get('last-modified') || '');
    if (!packed.ok || !(tg >= tp || !plain.ok)) throw new Error('gzip copy missing or stale');
    const bytes = new Uint8Array(await (await fetch(`${path}.gz`, { cache: 'no-store' })).arrayBuffer());
    const text = bytes[0] === 0x1f && bytes[1] === 0x8b
      ? await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).text()
      : new TextDecoder().decode(bytes);
    return JSON.parse(text);
  } catch (error) {
    const r = await fetch(path, { cache: 'no-store' });
    if (!r.ok) throw new Error(`${path} : HTTP ${r.status}`);
    return r.json();
  }
}

/** Colour ramp (low -> high) for 0..1. */
export function ramp(t, stops = ['#f7fcf5', '#c7e9c0', '#74c476', '#238b45', '#00441b']) {
  if (!Number.isFinite(t)) return '#cccccc';
  t = Math.min(1, Math.max(0, t));
  const i = Math.min(stops.length - 2, Math.floor(t * (stops.length - 1)));
  const f = t * (stops.length - 1) - i;
  const a = hex(stops[i]), b = hex(stops[i + 1]);
  return `rgb(${a.map((x, k) => Math.round(x + (b[k] - x) * f)).join(',')})`;
}
const hex = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
export const DIVERGING = ['#2166ac', '#92c5de', '#f7f7f7', '#f4a582', '#b2182b'];

/** Minimal SVG line chart: series = [{label, points:[[x,y]...], color}] */
export function lineChart(series, { yLabel = '', baseline = null } = {}) {
  const all = series.flatMap(s => s.points).filter(p => Number.isFinite(p[1]));
  if (!all.length) return '<p class="micro">Pas de données.</p>';
  const W = 520, H = 180, L = 42, R = 10, T = 10, B = 24;
  const xs = all.map(p => p[0]), ys = all.map(p => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const sx = x => L + (x - x0) / ((x1 - x0) || 1) * (W - L - R);
  const sy = y => H - B - (y - y0) / ((y1 - y0) || 1) * (H - T - B);
  const ticks = [y0, (y0 + y1) / 2, y1];
  let svg = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(yLabel)}">`;
  ticks.forEach(t => { svg += `<line x1="${L}" x2="${W - R}" y1="${sy(t)}" y2="${sy(t)}" stroke="#e6ebe3"/><text x="${L - 4}" y="${sy(t) + 3}" text-anchor="end">${fmt(t, Math.abs(y1 - y0) < 5 ? 1 : 0)}</text>`; });
  [x0, Math.round((x0 + x1) / 2), x1].forEach(t => { svg += `<text x="${sx(t)}" y="${H - 6}" text-anchor="middle">${t}</text>`; });
  if (baseline != null) svg += `<line x1="${L}" x2="${W - R}" y1="${sy(baseline)}" y2="${sy(baseline)}" stroke="#999" stroke-dasharray="4 3"/>`;
  series.forEach(s => {
    const pts = s.points.filter(p => Number.isFinite(p[1]));
    svg += `<polyline fill="none" stroke="${s.color || '#2f7d5b'}" stroke-width="${s.width || 1.6}" points="${pts.map(p => `${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join(' ')}"/>`;
  });
  return svg + `<text x="${L}" y="${T + 2}">${esc(yLabel)}</text></svg>`;
}

export function partnerKey() { try { return localStorage.getItem('renatura-partner-key') || ''; } catch { return ''; } }
export function setPartnerKey(v) { try { localStorage.setItem('renatura-partner-key', v); } catch { /* private mode */ } }
