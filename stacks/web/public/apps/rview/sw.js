const CACHE = 'rview-v2';
const ASSETS = [
  '/apps/rview/',
  '/apps/rview/index.html',
  '/apps/rview/app.css',
  '/apps/rview/app.js',
  '/apps/rview/manifest.json',
  '/apps/rview/icon-192.svg',
  '/apps/rview/icon-512.svg'
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(clients.claim());
});

self.addEventListener('fetch', (e) => {
  e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
});
