# Dispatch outcome — timer-alert-idc03-chaba-jobs (duplicate dispatch)

## Finding: FALSE ALARM — do NOT re-enable

`chaba-jobs.timer` on idc03 being **disabled is deliberate**. It is the
intended end-state of OPS-0790: Tony approved (2026-10-29) migrating all
`dispatch:dispatcher` jobs to per-job rendered systemd timers and retiring
the legacy 1-min dispatcher tick. Zero `dispatch:dispatcher` entries remain
in `ssot.jobs.yml`.

This exact card was already investigated and resolved by dispatch
`20261108-131205` ~4 min before this session started; its fix is merged
into this worktree's base (commits `f2a7ee773`, `5976eb0c2`). The alert
was a stale-declaration false positive: `chaba-jobs` sat in
`timer-sentinel.py`'s hardcoded `CRITICAL` set, so any disabled unit by
that name was carded regardless of census. The fix dropped it from
CRITICAL and added an idc03 census entry
`chaba-jobs.timer expected_state: inactive` in
`docs/ssot/infrastructure/ssot.audit.hosts.yml`.

## Live verification (this session, ~13:25 +07)

- `ssh idc03 systemctl --user is-enabled chaba-jobs.timer` → `disabled`,
  `is-active` → `inactive` — matches the new census declaration.
- Replacement timers armed and firing on idc03:
  - `yomi-update-active.timer` — fired 11 min ago, next in 3 min
  - `embed-lane-news.timer` — fired 31 min ago, next in 28 min
  - `embed-lane-lessons.timer` — daily, next in ~2.5 h
- Nothing is starved; no action taken on the unit (re-enabling was
  explicitly NOT the chosen option — the unit is retired).

## Actions taken this session

1. Re-verified live state on idc03 (above).
2. Confirmed the merged fix is present in the worktree
   (`scripts/ada/timer-sentinel.py` CRITICAL set, idc03 census entry).
3. Posted evidence comment to `timer-alert-idc03-chaba-jobs`.
4. Moved the card `backlog → review` via board-api `do=move` — keeps the
   card in the sentinel's open-ids set so the stale sentinel on tony-omen
   (pre-repo-sync) only comments instead of re-queueing a dispatch;
   `review_kind: verify` lets merge-sweep auto-close it.

## Residuals (inherited from the 131205 session — not new work)

- Stale sentinel on tony-omen keeps commenting "[still suspicious]" until
  `chaba-repo-sync` pulls the merged fix to that exec checkout (~15 min
  cadence) — cosmetic, self-resolves.
- tony-dell `chaba-jobs.timer` stays enabled+active (no-op tick) until
  rollout step-3; its census entry remains `expected_state: active`.
- tony-dell `lesson-drift-check.timer` is installed but never armed —
  separate gap, surfaced on parent card
  `chaba-jobs-dispatcher-dead-fleet-wide-di-765e5b`.
- idc03 `chaba-jobs.{service,timer}` unit files remain on disk pending
  the OPS-0790 cleanup commit; if deleted, flip census to
  `expected_state: absent`.

## How to verify

- `ssh idc03 systemctl --user list-timers | grep -E 'embed-lane|yomi-update-active'`
  — all NEXT/LEFT populated.
- Card `timer-alert-idc03-chaba-jobs` stops receiving "[still suspicious]"
  comments after tony-omen's next `chaba-repo-sync`, then merge-sweep
  closes it.
- Trail: `docs/ssot/jobs/infrastructure/2026-11-08-chaba-jobs-timer-idc03-retired-false-alert.yml`
