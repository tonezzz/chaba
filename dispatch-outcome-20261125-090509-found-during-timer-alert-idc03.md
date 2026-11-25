# Dispatch outcome — provider-gate-zombie-backend-blind

Card: `provider-gate-zombie-backend-blind` (docs/ssot/kanban/cards/provider-gate-zombie-backend-blind.yml)
Branch: `dispatch/20261125-090509-found-during-timer-alert-idc03` — commit `a23aee3da3` (not pushed, per dispatch rails)

## What changed

`scripts/ada/scenario-provider-gate.py` gained a live-serving probe so a
systemd-active but dead backend can no longer verdict `ok`:

- `service_port(unit)` — resolves the backend listen port from the unit's
  `ADA_PORT` env, falling back to `--port` in ExecStart (same resolution
  as ada-voice `scripts/deploy-ada.sh service_port()`). Empty → probe
  verdict `skip`, preserving the journal-only path for relays/non-HTTP
  units.
- `check_live_probe(unit)` — GET `http://127.0.0.1:<port>/api/health`,
  2 attempts x 4s timeout, 1.5s apart; requires HTTP 200 + JSON
  `ok:true` (the unauthenticated pwa_server.py health contract, in prod
  since 2026-10-14). Failure → `infra`.
- Verdict chain: `not active → infra`; `live==infra → infra`;
  `paid-lane → paid-lane`; `quota-dead → quota-dead`; else `ok`.
  The `infra` reason carries the probe detail, so the per-scenario
  `infra` reports + gate summary doc show the zombie evidence.

## Decision (card offered two fix directions — picked one)

Chose **option B (cheap live probe)** over option A (journal-silence
floor). Rationale: journal silence is not evidence of death — an
idle-but-healthy backend also logs nothing between suite runs, so a
`healthy_markers==0 && journal_lines<floor` rule would false-skip quiet
nights. `/api/health` proves the exact surface the suite needs and also
catches zombies that *do* have recent journal markers (hung after the
last log line) — the floor could not. Documented in
`docs/ssot/jobs/ada/2026-11-25-provider-gate-zombie-backend.yml`.

## Files

- `scripts/ada/scenario-provider-gate.py` — probe + verdict wiring + docstring
- `tests/ada/test_scenario_provider_gate.py` — 9 new unit tests
- `docs/ssot/jobs/ada/2026-11-25-provider-gate-zombie-backend.yml` — decision trail

## Verification

- `python3 -m pytest tests/ada/test_scenario_provider_gate.py -x -q` → **9 passed**
- `python3 scripts/ada/scenario-provider-gate.py --unit ada-dev --dry-run` on
  idc02 → clean `infra` verdict (unit inactive here), exit 1, new
  `live_probe:` check line prints correctly.
- Live proof lands on the next scheduled suite fire on idc03: a zombie
  ada-dev now gates `infra` (clean skip + per-scenario infra reports)
  instead of `ok`.

## Notes for reviewer

- Probe adds ≤ ~10s worst case to ExecCondition; loopback only, zero API
  spend — consistent with the gate's "zero spend" contract.
- `infra` is already in `REPORT_STATUSES`, so skip reporting needed no
  changes.
- No `pipeline: ci` field on the card — card-pipeline.py not run.

lessons:
- ada-voice pwa_server.py exposes unauthenticated GET /api/health (ok:true + active_sessions) on every backend port — the cheap liveness surface for any is-active-is-not-proof gate; deploy-ada.sh already drains on it.
- systemd is-active + journal-quiet is not liveness: a zombie uvicorn stays 'active' forever; probe the serving surface, don't infer from logs.
- Journal-silence floors false-positive on idle backends — absence of log lines between hourly suite runs is normal, not evidence of death.
- YAML jobs-trail files: `name: value` inside a `- ` sequence item parses as a nested mapping and breaks on continuation lines — use `>-` folded scalars for `func(args): desc` bullets.
