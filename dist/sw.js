/* Versioned same-origin cache. No background computation or telemetry. */
const VERSION = 'renatura-catalog-graph-20261111-v7';
const CORE = [
  './', './index.html', './styles.css', './app.js', './core.js', './i18n.js',
  './orientation.js', './orientation.css', './catalog-ui.js', './custom-data.js', './data/orientation/cities.json',
  './vendor/leaflet/leaflet.js', './vendor/leaflet/leaflet.css',
  './map.js', './documents.js', './worker.js', './maplibre-gl.js', './maplibre-gl.css',
  './icon.svg', './manifest.webmanifest',
  './data/cells.geojson', './data/summary.json', './data/scenarios.json',
  './data/connectivity.json', './data/sensitivity.json', './data/data_catalog.json',
  './data/boundary.geojson', './data/manifest.json',
];
const OPTIONAL = [
  './data/woodland.geojson', './data/routes.geojson', './data/hedges-1947.geojson',
  './data/hedges-2010.geojson', './data/hedges-2016.geojson',
];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(VERSION).then(cache => cache.addAll(CORE)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(
    keys.filter(key => key.startsWith('renatura-') && key !== VERSION).map(key => caches.delete(key)),
  )).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/')) return;  // never cache API answers
  // Network first for EVERYTHING (pages, scripts, styles, data are all edited/rebuilt in place under the same
  // names); the cache is only an offline fallback. Large data files (> 25 MB) are not copied into the cache.
  event.respondWith(fetch(event.request).then(response => {
    const size = Number(response.headers.get('content-length') || 0);
    if (response.ok && size < 25e6) {
      const clone = response.clone();
      event.waitUntil(caches.open(VERSION).then(cache => cache.put(event.request, clone)));
    }
    return response;
  }).catch(() => caches.match(event.request)));
});
self.addEventListener('message', event => {
  if (event.data.type !== 'CACHE_LAYERS') return;
  event.waitUntil(caches.open(VERSION).then(cache => cache.addAll(OPTIONAL))
    .then(() => event.ports[0]?.postMessage({ ok: true }))
    .catch(error => event.ports[0]?.postMessage({ error: error.message })));
});
