const CACHE = 'apps-v2';
const SHELL = [
  '/apps/',
  '/apps/index.html',
  '/apps/apps.yml',
  '/apps/manifest.json',
  '/apps/icon.svg',
  '/apps/icon-192.png',
  '/apps/icon-512.png',
  '/apps/apple-touch-icon.png',
  '/apps/favicon.ico'
];
const CDN = [
  'https://cdn.tailwindcss.com',
  'https://cdn.jsdelivr.net/npm/js-yaml@4.1.0/dist/js-yaml.min.js'
];

function cacheKey(req) {
  const url = new URL(req.url);
  url.search = '';
  return new Request(url.href, { method: req.method });
}

self.addEventListener('install', (e) => {
  e.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE);
      await cache.addAll(SHELL).catch((err) => console.warn('[sw] shell cache addAll failed', err));
      for (const url of CDN) {
        try {
          const res = await fetch(url, { mode: 'no-cors' });
          if (res) await cache.put(url, res);
        } catch (err) {
          console.warn('[sw] cdn cache failed', url, err);
        }
      }
      await self.skipWaiting();
    })()
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    (async () => {
      for (const key of await caches.keys()) {
        if (key !== CACHE) await caches.delete(key);
      }
      await self.clients.claim();
    })()
  );
});

function isDynamic(url) {
  const p = url.pathname;
  return p.includes('/api/') || p.endsWith('/ws') || p.endsWith('/websocket');
}

function isHtmlOrManifest(req, url) {
  if (url.pathname === '/apps/apps.yml') return true;
  if (url.pathname.endsWith('/manifest.json') || url.pathname.endsWith('/manifest.webmanifest')) return true;
  if (req.mode === 'navigate') return true;
  const accept = req.headers.get('accept') || '';
  return accept.includes('text/html');
}

async function networkFirst(req) {
  const key = cacheKey(req);
  const cache = await caches.open(CACHE);
  try {
    const network = await fetch(req);
    if (network && network.status === 200) cache.put(key, network.clone());
    return network;
  } catch (e) {
    const cached = await cache.match(key);
    if (cached) return cached;
    throw e;
  }
}

async function cacheFirst(req) {
  const key = cacheKey(req);
  const cache = await caches.open(CACHE);
  const cached = await cache.match(key);
  if (cached) {
    fetch(req).then((res) => {
      if (res && res.status === 200) cache.put(key, res);
    }).catch(() => {});
    return cached;
  }
  const res = await fetch(req);
  if (res && res.status === 200) cache.put(key, res.clone());
  return res;
}

async function staleWhileRevalidate(req, urlStr) {
  const cache = await caches.open(CACHE);
  const cached = await cache.match(urlStr);
  const fetchPromise = fetch(req, { mode: 'no-cors' }).then((res) => {
    if (res && (res.type === 'opaque' || res.status === 200)) cache.put(urlStr, res.clone());
    return res;
  }).catch(() => cached);
  return cached || fetchPromise;
}

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  if ((req.headers.get('Upgrade') || '').toLowerCase() === 'websocket') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) {
    if (CDN.includes(url.href)) {
      e.respondWith(staleWhileRevalidate(req, url.href));
    }
    return;
  }

  if (!url.pathname.startsWith('/apps/')) return;
  if (isDynamic(url)) return;

  if (isHtmlOrManifest(req, url)) {
    e.respondWith(networkFirst(req));
    return;
  }

  e.respondWith(cacheFirst(req));
});
