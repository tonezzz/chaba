# Dispatch outcome — timer-alert-idc03-chaba-jobs (second duplicate dispatch, idc02)

## Verdict

`chaba-jobs.timer` on idc03 being disabled is **deliberate** — the approved
end-state of OPS-0790 (legacy dispatcher retired, all jobs on per-job
rendered timers). Do NOT re-enable it. This is now confirmed three times:
dispatch 131205 (fix merged), dispatch 131613 on tony-macbook (parallel
duplicate), and this session.

## What this session found/did

- **Live re-verification on idc03 (~13:21 +07):** `chaba-jobs.timer` =
  `disabled`/`inactive`; replacements armed and firing —
  `yomi-update-active` (11 min ago), `yomi-update-all` (17 min),
  `embed-lane-news` (31 min), `embed-lane-lessons` (daily, 21h ago).
  Nothing starved.
- **Fix confirmed merged:** this worktree's base already contains the
  131205 branch (sentinel `CRITICAL` no longer lists `chaba-jobs`; idc03
  census entry `expected_state: inactive`; trail file
  `docs/ssot/jobs/infrastructure/2026-11-08-chaba-jobs-timer-idc03-retired-false-alert.yml`).
- **Card closed:** `timer-alert-idc03-chaba-jobs` is now `column: done`,
  `action.status: done` (sibling session moved it to `review`;
  merge-sweep auto-closed).
- **Duplicate dispatch observed + carded:** kanban-dispatch spawned TWO
  sessions on this card 28s apart — devin-task-20261108-131613
  (tony-macbook) and this one, -131641 (idc02). During the same window a
  `/action do=close` that returned `{"ok":true,"moved to done"}` was later
  absent from the card (state read `backlog`/`queued`), and POST /action
  hung >30s behind the board write flock (each write does git commit +
  render-board; merge-sweep + kanban-dispatch + a hung local /comment
  curl were all contending). Filed as
  `kanban-dispatch-spawned-duplicate-sessio-f49ed8` (KNB-1196, backlog).

## Residuals

- **Stale sentinel noise:** tony-omen's exec checkout still has the old
  `timer-sentinel.py` (`chaba-jobs` in CRITICAL — verified via ssh), so it
  keeps posting `[still suspicious]` on the (now done) card until
  `chaba-repo-sync` pulls master there. Cosmetic, self-resolves.
- **tony-dell rollout gaps (inherited, tracked on
  `chaba-jobs-dispatcher-dead-fleet-wide-di-765e5b`):**
  `lesson-drift-check.timer` installed but never armed;
  `chaba-jobs.timer` still enabled doing no-op ticks pending step-3
  disable.
- **idc03 unit files:** `~/.config/systemd/user/chaba-jobs.{service,timer}`
  remain; removal is part of the OPS-0790 cleanup commit (flip census to
  `expected_state: absent` if deleted).

## How to verify

```
ssh idc03 systemctl --user list-timers | grep -E 'embed-lane|yomi-update'
# board: card timer-alert-idc03-chaba-jobs shows column=done
# sentinel heartbeat stops commenting after tony-omen's next chaba-repo-sync
```
