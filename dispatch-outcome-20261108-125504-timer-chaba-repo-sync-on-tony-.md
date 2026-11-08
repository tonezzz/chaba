# dispatch 20261108-125504 — timer chaba-repo-sync on tony-dell failing

Card: `timer-alert-tony-dell-chaba-repo-sync` (OPS-1169). Runner: idc02.

## Verdict: duplicate dispatch — already resolved, re-verified clean

This session is a **zombie-claim restart** (OPS-1071): the first dispatch
(`devin-task-20261108-124119`) committed its claim but its response was
lost, so chaba re-dispatched the same card at 12:55 — minutes after the
first session had already finished, merged, and moved the card to
`review` (action.status=done, verified=true).

## What the first dispatch found/fixed (confirmed, not re-done here)

`chaba-repo-sync.service` on tony-dell wedged all morning (timeout at
10:42 / 11:28 / 12:02, exit-code at 10:54 / 11:41 / 12:15, signal at
12:33). Root cause: an **orphaned `board-api.py`** (spawned ~Nov 4 in
the devin-desktop scope; the real `chaba-board-api.service` is
`.parked` on dell by design) kept listening on `127.0.0.1:8787` bound to
`~/CascadeProjects/chaba` — the **exec** checkout, not the canonical
served checkout on idc03. Every dell-side caller defaulting to
loopback:8787 (timer-sentinel, board-cli, reconcile) wrote through it;
board-api's immediate `_commit_write` produced **837 unpushed local
commits** (10:31–12:19). Each 15-min `git pull --rebase --autostash`
then replayed the whole pile — card-union merge driver per conflict,
`.ref-seq.local-conflict-*` churn, slow-door flag posts — until
`TimeoutStartSec=300` SIGTERMed it.

Resolution (dispatch-124119): rogue process killed ~12:30 (PID 262964),
`git reset --hard origin/master` at 12:34 discarded the pile, lost-write
recovery replayed the real uniques to canonical board-api on idc03.
Full trail: `dispatch-outcome-20261108-124119-*.md` and
`docs/ssot/jobs/infrastructure/2026-11-08-chaba-repo-sync-timeout-rogue-board-api.yml`.

## Re-verified this session (live on tony-dell)

- `journalctl --user -u chaba-repo-sync.service`: post-fix ticks
  **12:35 (no-op), 12:51 (7.7s), 13:06 (8.6s)** — all `Result=success`,
  `ExecMainStatus=0`. Three consecutive clean ticks.
- `ss -tlnp | grep 8787` → nothing; `pgrep -af board-api` → nothing.
- `git rev-list --left-right --count HEAD...origin/master` → `0 0`
  (exec checkout converged).
- `chaba-repo-sync.timer` enabled, next fire on normal ~15-min cadence.
- Card state: `review`, verified. Stale sentinel "[still suspicious]"
  comms cited pre-fix runs only (last failure 12:33).

## Still-open residuals (carded in prior dispatch — not regressions)

- dell loopback-8787 default in timer-sentinel/board-cli/reconcile is a
  repeat-wedge trap (repoint to `board-cli --ssh idc03` or add canary).
- `~/.config/systemd/user/*.parked` units on dell violate
  declared-or-dead hygiene.
- Exec checkout uncommitted leftovers (staged focus-inbox file, modified
  `stacks/web/public/apps/ha/ssot.ui.ha.yml`, untracked kb doc) and 7
  retained autostash entries.
- ~30 stale worktrees on dell.

## Board trail

- Posted `[dup-dispatch 125504]` verification comments on
  `timer-alert-tony-dell-chaba-repo-sync` (progress + VERIFIED STALE).
- No card field moves — card already in review with verified action;
  workflow fields belong to humans/QC.

## Verify

```
ssh tony-dell 'journalctl --user -u chaba-repo-sync.service -n 20'   # <10s ticks, success
ssh tony-dell 'cd ~/CascadeProjects/chaba && git rev-list --left-right --count HEAD...origin/master'  # 0 0
ssh tony-dell 'ss -tlnp | grep 8787'                                 # empty
```
