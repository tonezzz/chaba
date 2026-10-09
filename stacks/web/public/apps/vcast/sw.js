// vcast display service worker.
//
// Version/bump strategy (makes stale-bundle playback impossible):
//   - Bump the cache name on EVERY deploy that changes a file under
//     /apps/vcast/ — activate deletes all older vcast-* caches.
//   - All same-origin /apps/vcast/ GETs are network-first WITH
//     cache:"no-cache" revalidation, so online clients always see the
//     current deploy (the display is useless offline anyway — it needs
//     the input-bridge ws; the cache is only a shell for offline loads).
//   - The ?v=N pins on the vendored <script> tags in index.html cover
//     the pre-SW first load, where heuristic HTTP caching can otherwise
//     serve a stale hls.min.js alongside fresh HTML.
//   - Cache name is vcast-* (not apps-*) so the shared /apps/sw.js
//     self-heal purge — which deletes all apps-* caches — leaves this
//     one alone.
const CACHE_NAME = "vcast-v5";
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
  event.waitUntil((async () => {
    // drop every previous vcast-* cache — a bumped name must not leave
    // the old bundle reachable
    const names = await caches.keys();
    await Promise.all(names
      .filter((n) => n.startsWith("vcast-") && n !== CACHE_NAME)
      .map((n) => caches.delete(n)));
    await self.clients.claim();
  })());
});

// Network-first for everything under /apps/vcast/ — HTML and vendored JS
// alike. The no-cache fetch forces a conditional revalidation (304 via
// ETag) instead of trusting heuristic HTTP caching, so a deploy can't
// strand a client on an old bundle while the relay is reachable.
// Everything else (API calls, media range requests, cross-origin) passes
// straight to the network — responding undefined on a cache miss +
// network fail is what Safari logs as "Load failed".
self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (url.origin !== location.origin) return;
  if (!url.pathname.startsWith("/apps/vcast/")) return;
  event.respondWith(
    fetch(event.request, { cache: "no-cache" }).then((r) => {
      if (r.ok) {
        const copy = r.clone();
        caches.open(CACHE_NAME).then((c) => c.put(event.request, copy));
      }
      return r;
    }).catch(() =>
      // ignoreSearch: navigations carry ?sid=/?_r=/?room= — the offline
      // fallback must still find the cached shell
      caches.match(event.request, { ignoreSearch: true })
    )
  );
});
