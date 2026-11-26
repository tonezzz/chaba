# Dispatch outcome — consumer-canary standing retired-hostname audit

Card: `consumer-canary-standing-retired-hostnam-6aa4a2` (OPS-0755)
Date: 2026-11-24 · Host: tony-macbook · Branch: dispatch/20261124-152422-consumer-canary-standing-retir

## What was found

The standing audit requested by this card was already implemented and live:
`scripts/audit/consumer-canary.py` runs via `consumer-canary.timer` on idc03
every 6h (verified: timer active, last run 13:51 today, journal shows CLEAN
runs since 2026-11-18). It greps deployed www bundles + unit envs on
tony-omen, caddy configs on idc02/mn01, unit envs on con01/idc03, and every
lovelace dashboard via websocket — for `tony-dell.taila0626a.ts.net` — and
posts findings to this card via board-api.

Two latent defects were fixed in the script:

1. **Blind-spot (the OPS-0731 failure mode itself):** `run()` discarded ssh
   return codes/stderr — a dead host, timeout, or grep error returned empty
   stdout and was counted as "no retired refs" → silent CLEAN. Now any
   rc>1 / timeout / dashboard SKIP is reported as an `UNAUDITABLE <surface>`
   finding on the card. All 10 audited paths were verified present on their
   hosts first, so rc>1 genuinely means a broken audit.
2. **Exit-code noise:** findings used to `exit 1`, which made every finding
   run look like a unit failure to timer-sentinel (spawned repeated
   timer-alert cards — the follow-up was already flagged in
   `docs/ssot/jobs/monitoring/2026-11-08-consumer-canary-timer-alert.yml`).
   Now exit 0 on any completed audit (board-api comms are the alert
   channel); exit 1 only when findings exist but the board-api post failed.
   Also split the chained mn01 grep into `mn01:caddy` + `mn01:units` so each
   surface gets its own audit status (9 greps → 10).

## Files changed

- `scripts/audit/consumer-canary.py` — unauditable-surface reporting, new
  exit semantics, mn01 grep split, docstring update.
- `docs/ssot/infrastructure/ssot.jobs.yml` — consumer-canary note updated
  with the new semantics.
- `docs/ssot/jobs/monitoring/2026-11-24-consumer-canary-hardening.yml` —
  decision/runbook trail.

## Verification

- `python3 -m py_compile` clean; `run()` unit-tested for dead-host (ssh
  resolve error → error), grep rc=2 (missing file/permission → error),
  and no-match (→ clean stdout).
- Full script copied to `idc03:/tmp` and run: `CLEAN (10 greps +
  dashboards)`, exit 0 — matches live journal behavior.
- Forced-findings run (`RETIRED_HOSTS=idc02...`, dead BOARD_API): findings
  listed, post failed → exit 1 as designed.
- Synthetic dead-host GREPS entry → `UNAUDITABLE dead:test: ssh: Could not
  resolve hostname...` emitted.
- Live state check: the last standing finding (`idc02:caddy-edge`
  reverse_proxy → tony-dell:8443, reported through 2026-11-18) is genuinely
  resolved — only remaining FQDN hit is a comment; upstream now
  `127.0.0.1:3000` (openchamber-migrate card).

## Deployment note

No unit changes needed (ExecStart path unchanged). idc03's exec checkout
pulls this via `chaba-repo-sync.timer` after merge; until then the timer
runs the old script — still correct, just blind to ssh failures and
exit-1 noisy on findings.

lessons:
- consumer-canary.py's run() used to discard ssh return codes — dead hosts
  read as CLEAN; audit scripts must treat rc>1/timeout as findings, not
  empty output.
- exit-1-on-findings in a systemd oneshot trips timer-sentinel into filing
  investigation cards even when the finding was already reported via
  board-api comms — report channels should own alerting, not exit codes.
- Chained `grep a; grep b` in one remote command masks the first grep's
  exit status — split audit targets into separate entries for per-surface
  status.
