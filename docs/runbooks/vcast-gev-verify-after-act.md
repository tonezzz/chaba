---
title: Verify-After-Act — GEV casts to vcast screens
description: A cast tool returning ok is not evidence. Every cast of /apps/gev/ to a screen must be followed by a state read proving the page rendered — this runbook defines the ground truths, the displaced-content tool contract, and the shared-SW stale-cache case.
tags: [vcast, gev, cast, verify-after-act, displaced-content, service-worker, runbook]
created: 2026-10-06
updated: 2026-10-06
category: operations
status: verified
last_verified: 2026-10-06
verification_method: exercised live against the tailnet deployment on screen 6 (vcast-real headless Chromium, idc02) — full sequence automated in stacks/web/input-bridge/gev-cast-verify.mjs, 14/14 PASS
scope: vcast displays (input-bridge relay on idc01), /apps/gev/ nav casts, ada-pi cast_to_screen displaced-content contract (feafff7), shared /apps/sw.js purge
owner: tony
related:
  [
    stacks/web/input-bridge/gev-cast-verify.mjs,
    stacks/web/input-bridge/vcast-cast-check.mjs,
    stacks/web/public/apps/vcast/index.html,
    stacks/web/public/apps/sw.js,
    stacks/tony-dell/gev-gemini/bridge.py,
    docs/ssot/apps/ssot.apps.vcast.yml,
    docs/ssot/jobs/gev/2026-10-06-gev-cast-verify-after-act.yml,
    docs/ssot/jobs/infrastructure/2026-10-06-vcast-sw-hls-audit.yml,
  ]
search_keywords: [verify after act, gev cast screen, displaced content camwall, vcast_list state read, uncapturable-iframe, apps-v6 stale cache]
---

# Verify-After-Act — GEV casts

**Abstract**: `POST /pub` returning `{"ok":true,"delivered":1}` only proves a
message reached a websocket — never that the screen shows the page. The
2026-10-04 transcript failure (5+ false "it's on the screen" claims) exists
because callers trusted tool output. The rule: **after every cast act, read
screen state before claiming.** This runbook is the GEV-cast instance of
that rule (kanban `gev-screens`, parent `verify-after-act`).

## The ground truths (what "verified" means)

A GEV cast is verified when **both** reads agree; either one alone is
weaker evidence.

| Read | Endpoint | Proof |
| --- | --- | --- |
| Relay registry | `GET /api/input-bridge/displays` | screen's `state:"nav"`, `state_detail` contains the GEV url **and** `pN:frame-ok` — `frame-ok` is set by the iframe's own `onload`, i.e. the page actually rendered (not just accepted). `frame-loading` = not done yet, keep polling. |
| GEV remote registry | `GET /apps/gev-cmd/command/health` | `remotes[]` contains `{screen:N, pane:P}` — the GEV page itself connected to the gev-gemini bridge as a passive remote (`?remote=1`). Its absence proves GEV is *not* on that screen even if other state lies. |

`vcast_list` in ada-pi surfaces `/displays`; `vcast_snapshot` surfaces the
`/frame` path below.

## The snapshot contract for nav casts

`nav` casts are iframes, and canvases can't read cross-origin frames — so
`snap-request` → `GET /frame` returns HTTP 200 with
`error:"uncapturable-iframe"`. **That is not a failure to verify**: the
`detail` field carries the live iframe `src` — for GEV it includes the
`screen=N&pane=P` params the display injected, which is direct evidence of
what's loaded. Only `video`/`image` casts return pixels.

Polling note: `GET /frame` answers `404 {"error":"frame not ready"}` until
the display's POST lands — keep polling, don't treat the first 404 as the
answer.

## Displaced-content tool contract (ada-pi feafff7)

Cross-repo contract — the detection side lives in ada-pi
`tool_runner.cast_to_screen`/`cctv_wall`; the ground truths live here.

- When a cast **over-writes** a pane whose current content is a GEV
  session (state read shows a `/apps/gev/` nav, or a `{screen,pane}`
  remote exists in `/command/health`), the tool returns `ok` **plus** a
  `displaced` note naming what was destroyed and a suggestion to use
  `layout` panes / PiP instead of a bare nav.
- Relay-side proof of displacement: the `pN:frame-ok` detail flips to the
  new URL **and** the GEV remote drops out of `/command/health` (the
  iframe teardown closes its ws). Both were observed live 2026-10-06:
  nav camwall over screen 6 GEV → `remote_screens` emptied within ~3s.
- The suggested remediation works verbatim:
  `layout {panes:2, mode:"pip"}` + `nav pane:0 /apps/gev/` +
  `nav pane:1 /apps/camwall/` → `panes:2`, `p0:frame-ok p1:frame-ok`,
  remote `{screen:6, pane:0}` re-registers.
- `gev_tour`/GEV guidance: never `cctv_wall` over a GEV session — take a
  pane instead.

## Shared /apps/sw.js stale-cache case (apps-v6)

2026-10-04 incident: older `/apps/sw.js` generations cached pages under
`apps-v*` names **with query strings stripped**, so `?v=N` cache-busting
never busted and stale GEV/app pages could persist indefinitely on cast
displays.

Current contract (deployed == repo):

- `/apps/sw.js` registers **no fetch listener** (no caching at all — a
  bare `respondWith(fetch())` only adds Safari console noise) and, on
  `activate`, deletes **every** `apps-*` cache — self-heal for any client
  that ever ran a caching generation.
- `/apps/vcast/sw.js` deliberately caches under `vcast-*` names — outside
  the `apps-*` namespace so the purge leaves it alone — network-first
  with `cache:"no-cache"` revalidation for all same-origin GETs.
- `gev/index.html` registers `/apps/sw.js?v=6` with scope `/apps/` —
  loading any /apps/ page on a client purges its stale `apps-v6` cache.

## Running the check

```bash
# full sequence against live: cast -> both state reads -> snapshot ->
# displace -> split/PiP remediation -> restore to idle
node stacks/web/input-bridge/gev-cast-verify.mjs            # screen 6 default
node stacks/web/input-bridge/gev-cast-verify.mjs --screen 7 # another lab screen
```

Requirements: a **connected** display on the target screen (screens 6-9 =
`vcast-real@idc02` lab displays; 2/4 = headless). The script also WARNs
when deployed `sw.js` files differ from this repo — it caught the
vcast-v2/vcast-v3 deploy drift on 2026-10-06.

Manual equivalent (what the script does, for a one-off):

```bash
B=https://tony-dell.taila0626a.ts.net/api/input-bridge
curl -X POST $B/pub -d '{"screen":6,"msg":{"type":"nav","url":".../apps/gev/"}}' -H 'content-type: application/json'
curl $B/displays | jq '.screens[] | select(.screen==6) | {state,state_detail}'
curl https://tony-dell.taila0626a.ts.net/apps/gev-cmd/command/health
```
