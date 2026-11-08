# Dispatch outcome — timer-alert-idc03-chaba-jobs (OPS-1148)

## Verdict

`chaba-jobs.timer` on idc03 being disabled is **deliberate** — it is the
approved end-state of OPS-0790. Do NOT re-enable it.

## What was found

- Tony approved on 2026-10-29 (card `chaba-jobs-dispatcher-dead-fleet-wide-di-765e5b`):
  migrate all `dispatch: dispatcher` jobs to per-job rendered systemd timers
  and retire the legacy dispatcher. Zero `dispatch: dispatcher` entries
  remain in `ssot.jobs.yml`.
- Verified live on idc03 (ssh, 2026-11-08 ~13:15 +07): `chaba-jobs.timer`
  is `disabled`/`inactive`, and all three idc03 replacements are armed and
  firing — `embed-lane-news` (ran 27min ago), `embed-lane-lessons` (21h,
  daily), `yomi-update-active` (6min). Nothing is starved.
- The alert was a **false positive**: `chaba-jobs` was still in
  `timer-sentinel.py`'s hardcoded `CRITICAL` set, which cards any disabled
  unit by name even without a census declaration. idc03 had no census entry,
  so CRITICAL alone triggered the card.
- Bonus finding on tony-dell (rollout gap): `chaba-jobs.timer` is still
  enabled+active doing no-op ticks (per plan until all 8 replacements
  verified), BUT `lesson-drift-check.timer` is installed yet **disabled** —
  never armed, so that job has silently not run since 10-29. Reported on the
  parent card; enabling it + census-declaring it is the remaining rollout
  step before the step-3 `disable --now chaba-jobs.timer` on dell.

## What changed (committed on this dispatch branch)

- `scripts/ada/timer-sentinel.py` — removed `chaba-jobs` from `CRITICAL`.
  tony-dell coverage is preserved via its census `expected_state: active`.
- `docs/ssot/infrastructure/ssot.audit.hosts.yml`:
  - idc03: added `chaba-jobs.timer` entry, `expected_state: inactive`,
    documenting the retirement (do-not-re-enable).
  - tony-dell: note updated to reflect zero-job tick, pending step-3
    disable, and the lesson-drift-check gap.
- New trail record:
  `docs/ssot/jobs/infrastructure/2026-11-08-chaba-jobs-timer-idc03-retired-false-alert.yml`

## Verification performed

- `ssh idc03 systemctl --user list-timers` — replacements live, dispatcher
  disabled.
- Simulated sentinel logic against updated census: idc03 `disabled` → no
  card; idc02 `missing` → no card; tony-dell still covered (exp=active).
- YAML loads clean for both edited/new files; sentinel source parses.

## Residuals

- Sentinel keeps commenting "[still suspicious]" until this branch merges
  and reaches tony-omen's exec checkout (sentinel runs there) — cosmetic,
  self-resolves.
- idc03 `~/.config/systemd/user/chaba-jobs.{service,timer}` files remain;
  removal belongs to the OPS-0790 cleanup commit. If deleted, flip the
  census entry to `expected_state: absent`.
- tony-dell: `systemctl --user enable --now lesson-drift-check.timer` +
  census declaration, then the step-3 dispatcher disable — tracked on
  `chaba-jobs-dispatcher-dead-fleet-wide-di-765e5b`.

## How to verify after merge

```
ssh idc03 systemctl --user list-timers | grep -E 'embed-lane|yomi-update-active'
# sentinel heartbeat on tony-omen: findings no longer include this card
```
