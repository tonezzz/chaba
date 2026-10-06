# dispatch outcome — vcast-app (SW cache / pair QR / HLS retry audit)

## What changed

**`stacks/web/public/apps/vcast/sw.js`** — reworked to `vcast-v3`. Previously
the vendored libs (`hls.min.js` 415KB, `qrcode.min.js`) were cache-first with
no revalidation and old `vcast-*` caches were never deleted — a lib upgrade
plus network-first HTML meant new page code could run against a stale bundle
forever. Now every same-origin `/apps/vcast/` GET is network-first with
`fetch(req, {cache:'no-cache'})` (ETag revalidation — a deploy can't strand a
client while the edge is reachable), `activate` deletes older `vcast-*`
caches, and the offline fallback uses `ignoreSearch` so `?sid=`/`?_r=`/`
?room=` navigations still hit the cached shell. Bump rule (documented in the
file): bump `CACHE_NAME` on any deploy touching the app; `vcast-*` never
collides with the shared `/apps/sw.js` `apps-*` purge.

**`stacks/web/public/apps/vcast/index.html`** —
`?v=3` pins on the vendored script tags (covers the pre-SW first load where
heuristic HTTP caching could serve a stale lib), plus real HLS drop
recovery: fatal hls.js `NETWORK_ERROR` re-polls via `startLoad()`,
`MEDIA_ERROR` -> `recoverMediaError()` x2 then rebuild, other fatals ->
destroy + recreate — bounded backoff 1.5s->15s, reset on `playing`, each
retry reported as state `hls-retry` so `/displays` shows recovery instead of
a stale `playing`. The native-Safari path reloads the element on `error`
and on `ended` for live playlists only (`duration===Infinity` / early-end
heuristic — a legitimately finished VOD won't loop). Retry timers are
per-pane and cleared in `paneTeardown` so a retry can't resurrect a stopped
pane.

**`stacks/web/public/apps/vcast/pair.html`** — `api()` now aborts at 10s and
surfaces a retryable error; previously a hung relay left the button stuck at
"pairing…" forever, silently eating the pair->play <10s budget.

**`stacks/web/input-bridge/server.mjs`** — real bug found by the new check:
`broadcastTo()` early-returned when the room had no clients (the room entry
is deleted on last-leave), so a cast published while a display was
mid-reconnect was dropped from `lastCast` and the re-register replayed the
STALE earlier cast. lastCast bookkeeping now runs before the empty-room
bail.

**`stacks/web/input-bridge/vcast-cast-check.mjs`** (new) — repo-side check
in the style of `vcast-flap-check.mjs`: spawns real `server.mjs` on loopback
with a stubbed ada auth (status + keys POST + redeem 302). 15 assertions:
pending sid, `/pair-info`, `/claim` -> api_key over ws, re-register onto the
claimed screen (claim->registered ~0.1s incl. two ada hops — the <10s budget
is comfortable), play + pane-1 image delivery, capture-lease set/get/clear,
interrupt cast delivered while a lease is active (the interrupt gate itself
lives in ada-pi's tool_runner, not the relay), stop, and lastCast replay
after a ws flap.

**SSOT** — `ssot.apps.vcast.yml`: receiver-page section now documents the SW
strategy + HLS recovery; testing section lists both check scripts; fixed
three stale relay IPs (`100.102.134.91` is idc03 — the relay binds
`100.74.146.0`/idc01). Same fix in `ssot.health.home.api.yml`.
Trail: `docs/ssot/jobs/infrastructure/2026-10-06-vcast-sw-hls-audit.yml`.

## Result / verification

- `node vcast-cast-check.mjs` -> 15/15 PASS, exit 0 (ran `npm install` in
  `stacks/web/input-bridge/` — `ws` dep; node_modules is gitignored)
- `node vcast-flap-check.mjs` -> 7/7 PASS, no regression
- `node --check` clean on sw.js + extracted inline scripts of both pages
- Live relay (`http://100.74.146.0:3010`) healthy: 7 screens. Manual cast on
  lab screen 7: `image` cast -> `state=image` in <8s, `stop` -> `state=idle`.
- `cast_interrupt_gate`: the gate is Ada-side (ada-pi repo, not in this
  worktree); the `/capture` lease contract it depends on is exercised in the
  new check. Full scenario run belongs to the `vcast-scenarios` card.
- `scripts/ssot-validate-all.mjs`: my files all pass; 1 pre-existing error in
  an unrelated jobs file (`2026-10-05-board-request-notify.yml`).

## Not deployed

Dispatch mode — nothing pushed. The pages take effect on the next chaba sync
to the live `stacks/web/public` mount; `server.mjs` needs the idc01 quadlet
updated + `systemctl --user restart input-bridge` to take effect (page fixes
are safe either way — the relay fix only improves replay correctness).
