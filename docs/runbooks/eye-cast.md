---
title: Cast the Eye page — live in-browser detection overlay on screens/TV
description: How to put /apps/eye/ on a vcast screen or the real TV, how
  Ada reads the overlay via eye/latest, and what to check when it lies.
tags: [eye, vcast, cast, screenlive, detection, runbook]
created: 2026-10-07
updated: 2026-10-07
category: operations
status: active
last_verified: 2026-10-07
verification_method: code review + route/CMS live checks; TV lane not yet
  run end-to-end (deploy pending)
scope: /apps/eye/ page, vcast displays, cast-browser screenlive lane,
  ada-ha-scenario-reports bench/edge-* + eye/latest docs
owner: tony
related:
  [
    stacks/web/public/apps/eye/eye.js,
    scripts/eye/cast-eye.sh,
    scripts/eye/bench-edge-cms.py,
    stacks/services/cast-browser/cast-browser-server.mjs,
    docs/runbooks/vcast-gev-verify-after-act.md,
    docs/ssot/apps/ssot.apps.vcast.yml,
  ]
search_keywords: [eye page, cast yolo, ada_look, what do you see, edge vision,
  screenlive workspace, vms snap, camwall thumb]
---

# Cast the Eye page

`/apps/eye/` runs MediaPipe efficientdet-lite0 **in the viewing browser**
and draws labels on a canvas over the video. Zero server inference —
whoever displays the page does the compute.

## Sources

| `?src=` | feed | notes |
|---|---|---|
| `me` | device camera (getUserMedia) | real seat/iOS Safari only — not in iframes, not headless |
| `cam:<name>` | `cameras.json` HLS via hls.js (native on iOS) | public traffic cams are CORS-blocked for hls.js on desktop |
| `snap:<name>` | frigate `latest.jpg` 2s poll | weakest devices |
| `snap:<zone>/<key>` | camwall last-good thumb 2s poll | **xmeye/DVR channels** (vms-noble-club, vms-noble-a, ...) + every pulled zone |
| `vms:<channel>` | fresh xmeye frame via `/apps/vms-snap` proxy | ~10s/capture on mn01 VMS desktop, serial |
| `test` | synthetic animated frames | no camera needed; bench-safe |

Other params: `?bench=N` (N-frame bench → MDDB `bench/edge-*`),
`?pub=N` (rewrite `eye/latest` every N s for ada_look).

## Lanes

### vcast screen (any paired display — incl. lab screens 6/7)

```bash
scripts/eye/cast-eye.sh screen 6 "src=test&bench=60&pub=10"
```

or raw:

```bash
curl -X POST https://tony-dell.taila0626a.ts.net/api/input-bridge/pub \
  -H 'Content-Type: application/json' \
  -d '{"screen":6,"msg":{"type":"nav","url":"/apps/eye/?src=test&pub=10"}}'
```

Verify-after-act: `GET /api/input-bridge/displays` — the screen must show
`state:"nav"` with `p0:frame-ok` in `state_detail` (frame-ok is set by the
iframe's own onload — proof the page rendered, same contract as GEV).
`snap-request`/`/frame` returns `uncapturable-iframe` for nav casts — that
is expected, not a failure.

### Real TV (Chromecast, media_player.tony_tv_cast)

```bash
scripts/eye/cast-eye.sh tv 4 "src=cam:doh_vibhavadi&pub=10"
```

This opens fullscreen Chrome on **tony-omen workspace 4** (ssh, DISPLAY=:0)
then `POST cast-browser/nav {url:"tony-omen:workspace:4"}` — omen's
cast-desktop@0 x11grabs the workspace to HLS and HA camera.play_stream
puts it on the TV. Detection runs in omen's desktop Chrome; the overlay is
baked into the HLS frames. No server-side annotate/encode.

Stop: `cast-eye.sh stop tv` (navs to `off`) / `stop screen <N>`.

The plain `screenlive:workspace:N` target exists in cast-browser but its
`cast-desktop@1`/`camera.desktop_1` wiring predates the cast move to omen
(omen has only :0) — use `tony-omen:workspace:N` until that path is
re-validated.

## Ada reads it (phase 4)

With `&pub=N` the page rewrites
`ada-ha-scenario-reports` → `eye/latest` every N s:
`{ts, src, model, detections:[{cls,score,box}], ua, pub_s}`.
The ada-pi tool `ada_look` (handoff spec in
`docs/ssot/jobs/eye/2026-10-07-nest-edge-vision.yml`) GETs that doc and
answers "what do you see" — read-only; actions on detections stay behind
the existing confirm-gate tools (cctv_wall/cast_to_screen).

## Bench loop

Any device: open `…/apps/eye/?src=test&bench=60`. The row lands in
`ada-ha-scenario-reports` as `bench/edge-<ts>` and is trended by
`bench-edge-cms.py` (hourly `bench-edge-cms.timer`) into the `bench-edge`
CMS page + `/apps/reports/bench-edge-trend.png`.

## Failure modes

- **Bench/publish silent-fail** — `/apps/eye-mddb/v1/add` requires a
  tailnet identity (403 without it) and the route must be deployed to the
  web edge first. The page reports `MDDB <status>` in the bench panel.
- **cam: CORS** — public traffic cams only play via iOS native HLS;
  on desktop use `snap:`/`vms:` or cast lane.
- **vms: slow** — each frame is a ~10s VMS-desktop capture; 2s poll is
  serialized so it degrades to ~0.1 fps, not an error.
- **snap: staleness** — camwall thumbs are last-good by contract; a dead
  cam keeps showing its last frame (check the camwall age badge).
