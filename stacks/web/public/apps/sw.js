// Shared /apps/ service worker — keeps pages controllable so PWA install
// works, but deliberately does NOT intercept fetch: a bare
// respondWith(fetch()) re-throws network failures as Safari's
// "FetchEvent.respondWith received an error: Load failed" console noise and
// adds nothing over the native path. Per-app workers (e.g. /apps/vcast/)
// implement their own real caching.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
