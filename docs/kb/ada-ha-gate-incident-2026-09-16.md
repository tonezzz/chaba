# Incident Report — Unauthorized Gate Actuation via Ada HA REST API

**Date:** 2026-09-16
**System:** Ada HA voice assistant backend (`ada-ha-michael`, mn01, port 8003)
**Severity:** Medium — physical device actuated without user intent; no injury or damage
**Status:** Resolved; preventive controls deployed and verified

## Summary

Between 17:08 and 17:10 ICT, the electric gate at the Michael site was
commanded to open five times and jogged via its "My position" button six
times. The commands were not issued by voice, the Home Assistant UI, or a
physical remote. They came from an automated script loop on the tony-dell
host (tailnet `100.68.142.13`) calling the unauthenticated REST endpoint
`POST /api/tools/call` — 156 tool invocations in ~4 minutes, hitting every
registered tool including physical control tools.

## Timeline (ICT)

- **17:08:21** — script on tony-dell starts calling `POST /api/tools/call` in a loop
- **17:08:22–17:08:48** — gate commanded open + jogged via "My position" (gate moving)
- **17:09:17** — gate finishes moving; cover state returns to `unknown`
- **17:10:03–17:10:13** — second burst: gate opened + jogged again
- **17:10:42** — loop ends; no further gate commands since

## Root Cause

`/api/tools/call` and `POST /api/home-assistant/entities/{id}/power`
accepted unauthenticated requests and executed **any** registered tool —
including physical control tools — with no server-side safety checks.

The "ask the user to confirm before moving the gate" rule existed only in
the Gemini voice model's system prompt. Any non-voice client bypassed it
entirely. There was also no rate limiting and no audit logging of tool
arguments.

The gate cover itself reports `opening`/`closing` only while moving and
reverts to `unknown` at rest (Tuya curtain-type device, no position
feedback), which made the event history look inconsistent on first read.

## Detection

Found while reviewing the new HA event-log feature: repeated
`opening`/`unknown` transitions on `cover.gate_motor` did not match
expected usage. Correlated the HA history timestamps with the service
journal, which showed matching `httpx POST /api/services/cover/open_cover`
calls and 156 `POST /api/tools/call` access-log entries from
`100.68.142.13` (tony-dell).

## Fixes Deployed (verified live on both instances)

1. **API-key authentication** — `ADA_API_KEY` per instance;
   `X-Api-Key` header or `?api_key=` required for `/api/tools`,
   `/api/tools/call`, and `POST .../power`. Unauthenticated calls return 401.
2. **Server-side dangerous-device gate** — all actuating tools
   (`control_entity`, `control_cover`, `press_button`,
   `control_media_player`, `tv_action`) are rejected unless
   `confirmed=true` is passed for entities marked `dangerous`. Related
   entities inherit danger by object-id prefix, so the gate's jog button
   is covered too.
3. **Voice path enforcement** — Gemini tool calls for control tools now
   route through the same gate; the model must pass `confirmed=true`
   after explicit user confirmation. Safety is enforced in code, not only
   in the prompt.
4. **Rate limits** — sliding window: 5 control calls/min per entity,
   30/min global (`ADA_CONTROL_*` envs to tune).
5. **Read-only kill switch** — `ADA_READ_ONLY=true` disables all
   actuating tools for demo/customer-facing instances.
6. **Audit logging** — every tool call logged with name, args, and
   client IP; denials logged as warnings.

## Evidence

- `journalctl --user -u ada-ha-michael`: `POST /api/tools/call` ×156 from
  `100.68.142.13`; matching `cover/open_cover` and `button/press` calls.
- `GET /api/home-assistant/entity-events?entity_id=cover.gate_motor`:
  transitions `opening`→`unknown` matching the call times exactly.
- Post-fix verification: unauthenticated call → 401; dangerous cover
  without `confirmed=true` → `status: denied`.

## Recommendations / Follow-ups

- Identify the script that ran the sweep on tony-dell and either remove
  it or give it the instance API key (`X-Api-Key`).
- Add `ADA_API_KEY` to `ada-pi-pwa` on tony-dell (same codebase); the web
  UI now supports the key via `?api_key=` or a one-time prompt.
- Consider enabling `ADA_READ_ONLY=true` on any instance reachable by
  customers or demos.
- Resolved 2026-09-17: `get_logbook` works on both instances — HA 2026.x
  moved the endpoint to `GET /api/logbook?end_time=&period=<days>&entity=`
  (the old `/api/logbook/period/<ts>` path 404s); ada-pi tries the new form
  first and falls back for older HA.
- Long-term: a contact sensor or position-feedback motor on the gate
  would give true open/closed state instead of transient `opening`/
  `unknown`.

## References

- Code: `ada-pi` commits `8b6ca8f` (event logs), `55a80a0` (safety gate),
  `3fb570c` (UI api-key support)
- Env: `~/.config/secrets/ada-ha-{tony,michael}.env` on mn01
