// Offline support for weak signal: the app shell is cached; the last risk map, route, shelters and status
// responses are kept so a phone that loses signal still shows the most recent picture (marked by its timestamp).
const SHELL = 'floodevac-shell-v2';
const DATA = 'floodevac-data-v2';
const SHELL_FILES = [
  '/', '/static/css/app.css', '/static/vendor/leaflet/leaflet.css', '/static/vendor/leaflet/leaflet.js',
  '/static/vendor/chartjs/chart.umd.min.js', '/static/js/pages/console.js', '/static/icons/icon.svg', '/static/manifest.json',
];
const CACHED_API = ['/api/risk', '/api/route', '/api/shelters', '/api/status', '/api/gauges', '/api/stats', '/api/alerts', '/api/rainfall'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(SHELL_FILES)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => ![SHELL, DATA].includes(k)).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin || url.pathname === '/api/stream') return;
  if (CACHED_API.some((p) => url.pathname.startsWith(p))) {
    // network first, fall back to the last good response for the same endpoint
    e.respondWith(fetch(e.request).then((res) => {
      if (res.ok) {
        const copy = res.clone();
        caches.open(DATA).then((c) => c.put(url.pathname, copy));
      }
      return res;
    }).catch(() => caches.open(DATA).then((c) => c.match(url.pathname)).then((r) => r || Response.error())));
    return;
  }
  if (url.pathname.startsWith('/static/') || url.pathname === '/' || url.pathname === '/responder' || url.pathname === '/model') {
    // network first so a new release is picked up immediately; the cache is the offline fallback
    e.respondWith(fetch(e.request).then((res) => {
      if (res.ok) {
        const copy = res.clone();
        caches.open(SHELL).then((c) => c.put(e.request, copy));
      }
      return res;
    }).catch(() => caches.match(e.request).then((hit) => hit || Response.error())));
  }
});
