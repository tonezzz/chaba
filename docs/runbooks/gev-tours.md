---
title: GEV tours — defined flyover routes with verifiable checkpoints
description: A tour is a JSON file of ordered stops (locationId | query | lat/lon), per-stop dwell, and narration cues. gev-tour.mjs plays it on a GEV display through the gev-gemini /command relay and writes a checkpoint report a scenario can verify. No gods-eye-view repo change required.
tags: [gev, tours, flyover, vcast, checkpoints, scenario, runbook]
created: 2026-10-06
updated: 2026-10-06
category: operations
status: verified
last_verified: 2026-10-06
verification_method: live run on vcast-real-6 (relay screen 1) — world-landmarks tour, 7/7 checkpoints in order, 70.5s; plus gev-tour-selftest.mjs stub-relay suite 24/24
scope: gev-gemini /command relay (tony-dell :8790 via /apps/gev-cmd), vcast displays, stacks/web/input-bridge/gev-tour.mjs
owner: tony
---

# GEV tours

A **tour** is a declarative JSON route: ordered waypoints, dwell time per
stop, narration cues. The runner plays it on any display that has a
registered GEV remote and reports each checkpoint reached **in order** —
the report is the contract a scenario (gev-scenarios) verifies.

## Why no app change was needed

`stacks/tony-dell/gev-gemini/bridge.py` already exposes
`POST /apps/gev-cmd/command {name, args, screen?, pane?, wait?}` which
pushes a `function_call` frame to passive remote clients and collects
their `tool_response` frames (wait capped at 10 s).
`fly_to_location(waitForArrival:true)` returns `arrived:true` when the
camera lands — that is the whole playback primitive. The runner lives in
chaba (`stacks/web/input-bridge/gev-tour.mjs`), so the held
gods-eye-view repo is not on the critical path.

## Tour file format

`stacks/web/input-bridge/tours/*.json`:

```json
{
  "id": "world-landmarks",
  "title": "World landmarks flyover — Bangkok to San Francisco",
  "version": 1,
  "defaults": { "dwell_s": 8, "arrival_timeout_s": 45,
                "camera": { "viewMode": "overview" } },
  "stops": [
    { "id": "bangkok",
      "target": { "query": "Bangkok, Thailand" },
      "camera": { "viewMode": "overview", "rangeM": 60000 },
      "dwell_s": 8,
      "narration": "Bangkok — home base." },
    { "id": "golden-gate",
      "target": { "latitude": 37.8199, "longitude": -122.4783 },
      "camera": { "viewMode": "close", "rangeM": 5000 } },
    { "id": "globe-out", "tool": "zoom_to_globe", "dwell_s": 4 }
  ]
}
```

Per stop:

| field | meaning |
|---|---|
| `id` | required, unique — checkpoint id in the report |
| `target` | exactly one of `{locationId}` (preset enum), `{query}` (geocoded), `{latitude,longitude}` → `fly_to_location` |
| `tool` + `args` | alternative to `target`: any GEV tool (`zoom_to_globe`, `fly_route`, `move_camera` orbit, …). Non-flight stops checkpoint on delivery ack |
| `camera` | merged into `fly_to_location` args (`viewMode`, `rangeM`) |
| `dwell_s` | hold time after arrival (default `defaults.dwell_s`, else 6) |
| `arrival_timeout_s` | per-stop cap on the view-state poll (default 45) |
| `narration` | text cue — recorded on the checkpoint AND drawn on-map as a `label` annotation anchored at the stop (max 120 chars on-map; `narrate_on_map:false` to keep it report-only) |
| `annotate` | explicit `annotate_map` annotations fired on arrival (e.g. `highlight`, `route`, `area`); `persist:true` keeps them instead of the ~20 s fade |
| `wait_arrival` | `false` to fire-and-forget the flight (default true) |

## Checkpoint contract (what a scenario asserts)

`--report <path>` writes:

```json
{ "tour": {"id","title","version"}, "screen": 1, "pane": 0,
  "started_at": "...", "finished_at": "...", "duration_s": 70.5,
  "checkpoints": [
    {"seq":0, "id":"bangkok", "tool":"fly_to_location",
     "target":{...}, "ok":true, "arrived":true,
     "verification":"tool_response",
     "dispatched_at":"...", "reached_at":"...",
     "dwell_s":8, "narration":"...", "error":null}
  ],
  "reached_in_order": true, "ok": true }
```

- Checkpoints are appended strictly in stop order; `reached_at` is
  monotonically non-decreasing.
- `ok` / exit 0 only when **every** checkpoint arrived in order.
- `verification` says how arrival was proven: `tool_response`
  (`waitForArrival` ack within the 10 s relay window), `view_state`
  (flying→settled transition in `get_current_view_state` polls),
  `coord_match` (camera lat/lon within 0.5° of a numeric target),
  `delivered` (non-flight stop), or `dry_run`.
- A stop that never confirms within `arrival_timeout_s` fails honestly —
  the tour continues unless `--stop-on-fail`.

## Running

Prereq: a GEV page registered as a remote — cast it first
(`POST /api/input-bridge/pub {screen, msg:{type:"nav", url:"…/apps/gev/"}}`,
see vcast-gev-verify-after-act.md) or open `/apps/gev/` inside a vcast
pane. `GET /apps/gev-cmd/command/health` must list `{screen,pane}`.

```bash
node stacks/web/input-bridge/gev-tour.mjs \
  --tour stacks/web/input-bridge/tours/world-landmarks.json \
  --screen 1 --report /tmp/tour.json
# options: --pane N  --gev-cmd URL  --dwell-scale 0.5  --arrival-timeout 20
#          --stop-on-fail  --dry-run  --json
```

`--dry-run` validates the file and prints the exact command sequence —
use it when authoring a new tour.

## Verifying without a display

```bash
node stacks/web/input-bridge/gev-tour-selftest.mjs
```

Spins a stub `/command` relay and asserts the contract: ordered
checkpoints, monotonic `reached_at`, narration → `annotate_map`,
lat/lon passthrough, stuck-stop failure (`reached_in_order:false`,
exit 1), and refusal when no remote is registered.

## Authoring a new tour

1. Copy `tours/world-landmarks.json`, rename `id`, edit stops.
2. `node gev-tour.mjs --tour tours/<new>.json --dry-run` — fix any FAIL lines.
3. Live-smoke with `--dwell-scale 0.3` on a lab screen, then commit both
   the tour file and the report.
