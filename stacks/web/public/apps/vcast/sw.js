const CACHE_NAME = "vcast-v1";
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
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS)));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

// network-first for HTML so the receiver page always picks up deploys;
// cache-first only for static assets
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
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
  event.respondWith(
    caches.match(event.request).then((r) => r || fetch(event.request))
  );
});
