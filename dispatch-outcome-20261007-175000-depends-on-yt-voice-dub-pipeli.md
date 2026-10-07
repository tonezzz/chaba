# dispatch outcome — yt-dub-liam-e2e readiness

## What was done

Card `yt-dub-liam-e2e` is a voice-driven E2E scenario whose verify step
requires Tony present. A prior session already picked the clip
(LLALMFmabV4), built the Thai dub, and encoded the scenario YAML. This
session re-verified every headless-checkable precondition:

- **Dub asset**: `stacks/web/public/apps/yt-live/LLALMFmabV4-dub.mp4`
  (live host checkout) — valid mp4, 180s, 4.6MB, HTTP 200 at
  `/apps/yt-live/LLALMFmabV4-dub.mp4`.
- **cached-videos-report**: published `ada-cms-pages` doc (en, updated
  2026-10-07 17:30 ICT) already lists it under Playable dubs;
  `cached-videos-update.py --dry-run` renders the same block;
  `chaba-cached-videos.timer` active, next run ~18:00.
- **yt-live-api** :8791 `/health` ok, `/status` phase=complete.
- **Screen 2**: input-bridge `/displays` shows screen 2 = "Browser"
  display (key `screen-5`), connected + idle. `cast_to_screen(screen=2)`
  routes via `/pub {screen:2}` → room `vcast-2`.
- **Scenario**: `ada-pi/tests/scenarios-live/yt_dub_liam_e2e.yaml`
  present (4 turns, tier: full).

## Notable finding

Relay registry number drifted from `screen-N` key names: slots 1-4 map
to keys screen-6/5/7/1. Routing is by the numeric `screen` field (not
the name), so "screen 2" from Tony still lands on the Browser display —
but the mismatch could confuse Ada; she must route on `screen`, not on
the `screen-N` name. Documented in the job trail.

## Deliverables

- Job trail: `docs/ssot/jobs/yt-dub/2026-10-07-yt-dub-liam-e2e-readiness.yml`
- Card comms: readiness comment posted; board request raised asking Tony
  to run the live voice pass.
- This file.

## How to verify

- `curl -s http://127.0.0.1/apps/yt-live/LLALMFmabV4-dub.mp4 -o /dev/null -w '%{http_code}'` → 200
- `curl -s http://127.0.0.1:8791/status` → phase complete
- `curl -s http://100.102.134.91:3010/displays` → screen 2 connected
- Live pass: Tony asks Ada for the Liam+Noel clip → play on screen 2 →
  what's cached → stop.

## Blockers

The final verification is a live voice pass requiring Tony. No code
changes needed; nothing else is blocked.
