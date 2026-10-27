# Dispatch outcome — map-embed-tool, 2nd run (2026-10-27, key-gate execution)

## Context

First dispatch (14:02) staged **ada-voice drop 17 — `map_embed`** and
merged it to master. Tony answered the key-reuse request with
**"proceed"** at 15:38; the answer-sweep re-queued the card, spawning
this run. Job: resolve the `GOOGLE_MAPS_API_KEY` gate.

## What was found (the real answer to the key question)

The gev key **cannot be reused**. Probed on tony-dell sourcing
`~/.config/secrets/gev-google-maps.env` (status codes only — value
never entered the transcript):

| API | Result |
|---|---|
| Maps Embed | 403 "The provided API key is invalid" |
| Maps Static | 403 same |
| Geocode | REQUEST_DENIED same |
| Routes | 401 UNAUTHENTICATED |
| Maps JS bootstrap | returns loader unconditionally — not a validity signal |

Same verdict with and without a GEV referer. The value is `AQ.Ab8…`
(53 chars — same newer key shape as the AI Studio Gemini keys, which
were also probed on idc03 and also rejected). Can't distinguish
dead-key vs APIs-disabled from outside; either way **no existing key
works** and **no host has gcloud/GCP creds** — mint-or-enable is a
Tony-in-GCP-console step. Board request
`google-maps-api-key-needs-a-mint-gev-key-ee1fc7` carries the
click-path (enable Embed+Static+Routes → restricted key → drop-in at
`~/.config/secrets/tony-ha/backend.env` on idc03), options
key-in-env-idc03 ★ / enabled-gev-project / hold.

**Side finding:** the same value sits in `~/gods-eye-view/.env`
(fingerprint-verified identical) — GEV's Google layers may be silently
on its documented Esri fallback. Carded as
`gev-google-maps-key-suspect-dead-verify-be569a` (MED-0937, backlog).

## What changed (chaba worktree, commit `11fec2c53`)

- `docs/ssot/infrastructure/ssot.secrets.yml` — `gev-google-maps`
  flagged TESTED INVALID with probe detail; added the missing
  `~/gods-eye-view/.env` slot to the inventory.
- `integrations/ada-voice/README.md` — drop-17 env step now states the
  gev key was probed unusable and names the real drop-in point.
- `docs/ssot/jobs/ada/2026-10-27-map-embed-key-gate.yml` — job record:
  probe evidence, landing state, next steps.

## State of the drop (verified, not deployed — dispatch scope)

- `pytest tests/ada/test_map_embed_drop.py` — **21 passed** (uv venv).
- ada-voice `origin/main @ 56c67c1` still has `count_cap: 112` —
  `ssot.tool-surface.map_embed.patch` still applies; manifest lacks
  wp_read/wp_update/map_embed.
- **Landing queue:** drop 16 (cms-slug-derivation), wp_read/wp_update,
  drop 17 all pending one pass on tony-dell (ff-pull first — its local
  main is 12 behind; the second count_cap bump goes 113→114), then
  `deploy-ada.sh idc03`. `map_embed` is keyless-useful the moment it
  lands (OSM static + open-in-Maps); the key only unlocks interactive
  iframes / Google basemaps / road polylines — an env drop-in +
  `systemctl --user restart ada-ha-tony`, no redeploy.

## Board

Comment posted (probe findings + landing state). Request raised with
notification queued. Card remains held by the open request — correct.
