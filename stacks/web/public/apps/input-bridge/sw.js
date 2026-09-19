const CACHE_NAME = 'input-bridge-v1';
const ASSETS = [
  '/apps/input-bridge/',
  '/apps/input-bridge/index.html',
  '/apps/input-bridge/receiver.html',
  '/apps/input-bridge/manifest.json',
  '/apps/input-bridge/icon-192.png',
  '/apps/input-bridge/icon-512.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS))
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  event.respondWith(
    caches.match(event.request).then((response) => response || fetch(event.request))
  );
});
