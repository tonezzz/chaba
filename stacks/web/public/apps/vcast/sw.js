const CACHE_NAME = "vcast-v2";
const ASSETS = [
  "/apps/vcast/",
  "/apps/vcast/index.html",
  "/apps/vcast/pair.html",
  "/apps/vcast/manifest.json",
  "/apps/vcast/hls.min.js",
  "/apps/vcast/qrcode.min.js",
  "/apps/vcast/icon-192.png",
  "/apps/vcast/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS))
      .then(() => self.skipWaiting())  // activate immediately — don't wait
  );                                  // for old clients to close
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

// network-first for HTML so the receiver page always picks up deploys;
// cache-first only for the pinned ASSETS list. Everything else (API calls,
// media range requests, anything outside our own files) passes straight to
// the network — responding undefined on a cache miss + network fail is what
// Safari logs as "Load failed".
self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (url.origin !== location.origin) return;
  if (!url.pathname.startsWith("/apps/vcast/")) return;
  if (url.pathname.endsWith(".html") || url.pathname.endsWith("/")) {
    event.respondWith(
      fetch(event.request).then((r) => {
        const copy = r.clone();
        caches.open(CACHE_NAME).then((c) => c.put(event.request, copy));
        return r;
      }).catch(() => caches.match(event.request))
    );
    return;
  }
  if (!ASSETS.includes(url.pathname)) return;
  event.respondWith(
    caches.match(event.request).then((r) => r || fetch(event.request))
  );
});
