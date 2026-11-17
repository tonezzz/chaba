# dispatch-outcome — timer michael-dev-parity on tony-omen

Card: `timer-alert-tony-omen-michael-dev-parity` (doing). Runner: tony-dell.

## What was found

`michael-dev-parity.service` (daily 06:15, oneshot) runs
`python3 scripts/home-assistant/mirror-sweep.py --fail-on-missing` from the
exec checkout `~/CascadeProjects/chaba` on tony-omen. Journal for 11-16 and
11-17 shows the audit completes but exits 1:

    missing on michael-dev: 1
      [dev-missing:no-ha-source] script.turn_on

Root cause is a **linter false positive, not real entity drift**. The
`tony-test` dashboard on michael-dev
(`docs/home-assistant/dashboards/tony-test-current.json` ~line 8587) has a
button `tap_action` with `action: call-service`,
`service: script.turn_on`, `target.entity_id: script.dev_shutter_demo`.
`collect_entities()` collects every string matching the entity-id regex —
including service-name fields — so `script.turn_on` (a service, not an
entity, existing nowhere) was counted as a missing entity and
`--fail-on-missing` exited 1 every night.

The 16 `ha-missing` entries (`dev_*` simulation entities,
`weather.forecast_baan`) are informational only — they exist on dev by
design and are not counted by the gate.

Earlier card history: the 10-13 failure was a ws-close crash (fixed same
day); the wrong-port ECONNREFUSED was fixed via OPS-0040 / PR #173 (11-14).
This session closes the remaining false positive.

## What changed

`scripts/home-assistant/mirror-sweep.py` (commit `bb3011d5496` on branch
`dispatch/20261117-092515-timer-michael-dev-parity-on-to`):

- Added `SERVICE_KEYS = {"service", "perform_action"}` — skipped in
  `collect_entities` so service names in action blocks are never collected
  as entity ids. `perform_action` covers the newer dashboard action schema.

## Result / verification

- Ran the fixed script live from tony-dell against real michael-dev (ws)
  and michael-ha: `missing on michael-dev: 0`, **RC=0** (was RC=1).
- `python3 -m py_compile` clean; no existing tests cover this script.
- Board comment posted with root cause + verification evidence.

## How it lands / how to verify on the host

- The fix reaches tony-omen via merge of this dispatch branch + the hourly
  `chaba-repo-sync.timer` (verified active, Result=success, fetch works;
  checkout HEAD already current at 11-17 08:53 and carries the file's
  latest prior commit 7cb4796197). No push/deploy was done per dispatch
  rules.
- After merge + sync: `ssh tony-omen 'journalctl --user -u
  michael-dev-parity.service --since tomorrow'` should show
  `missing on michael-dev: 0` and `Result=success` at the 06:15 run, or
  manually: `ssh tony-omen 'cd ~/CascadeProjects/chaba && python3
  scripts/home-assistant/mirror-sweep.py --fail-on-missing; echo $?'`.

## Residual notes

- `~/CascadeProjects/chaba` on omen reported `behind 271` vs origin/master
  at first look, yet HEAD is current (11-17 08:53) and chaba-repo-sync is
  green — likely a stale tracking ref; sync demonstrably works.
- Card can be closed once a post-merge run goes green (tomorrow 06:15 at
  latest, assuming merge today).
