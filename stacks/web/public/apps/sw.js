// Shared /apps/ service worker — keeps pages controllable so PWA install
// works, but deliberately does NOT intercept fetch: a bare
// respondWith(fetch()) re-throws network failures as Safari's
// "FetchEvent.respondWith received an error: Load failed" console noise and
// adds nothing over the native path. Per-app workers (e.g. /apps/vcast/)
// implement their own real caching.
//
// Self-heal for the stale-cache incident (2026-10-04): earlier versions of
// this worker cached pages under 'apps-v*' names with query strings
// stripped, so ?v=N cache-busting never worked and old pages could persist
// indefinitely. On activate we purge every 'apps-*' cache so any client
// that ever ran a caching worker gets cleaned up. Per-app caches
// (vcast-* etc.) are untouched.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil((async () => {
  const names = await caches.keys();
  await Promise.all(names
    .filter(n => n.startsWith('apps-'))
    .map(n => caches.delete(n)));
  await self.clients.claim();
})()));
