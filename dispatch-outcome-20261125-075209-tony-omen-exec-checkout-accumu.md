# Dispatch outcome — omen-chaba-checkout-focus-inbox-writers-d993c4

## What changed

Root cause confirmed and fixed fleet-wide: focus-inbox writers ran against
checkouts that can never commit (`chaba-role` exec/readonly, or non-git
replica trees), so alerts piled up as invisible untracked files.

New shared guard: `scripts/lib/inbox_door.py`
- `checkout_role(root)` / `local_writes_ok(root)` — mirrors the pre-commit
  role guard; exec/readonly AND non-git dirs return False (the
  `~/CascadeProjects/chaba-tony-dell` tree on tony-omen is a non-git
  replica with 6327 stale inbox files — writes there were pure litter).
- `post_inbox(payload)` — POSTs to board-api `/inbox` (the unified write
  door; served checkout on idc03 commits it).

Writers guarded (route to /inbox or skip on non-committable checkouts):

| Script | Behaviour on exec/readonly/non-git |
|---|---|
| devin/render-handoff-inbox.py | skip (served run via kanban-commit) |
| report/report-watch.py | skip local writes; reads/dedup unchanged |
| audits/gh-runs-watch.py | POST /inbox per alert |
| arp-inventory-scan.py | POST /inbox |
| mcp-health-to-inbox.py | skip (canonical = served overnight) |
| ssot-optimize-to-inbox.mjs | skip (hardcoded dell path is non-git on omen) |
| mcp-health-snapshot.mjs | POST /inbox |
| focus_dispatcher/cli.py | hard gate — every mutating path ends in git_commit |
| overnight-focus-review.py | skips improvements-triage + ssot-optimize (tracked-file writers); validation still runs |
| overnight/promote-reports.py | skip drafts (served run is canonical) |
| mcp-link-monitor.py | POST /inbox (link-down + drift alerts) |
| audit-watchdog.mjs | skip inbox file writes; Events feed still alerts |
| audits/run.mjs | skip audit-failures.yml write/remove |
| mddb-binlog-canary.py | skips non-committable INBOX_CANDIDATES, falls back to POST /inbox |
| audits/ha-auth-watch.py | POST /inbox; --git commit also gated |
| board/board-invariants.py | POST /inbox with signature dedup (state file) |
| check-serve-config.py | POST /inbox with signature dedup |
| worktree-sync.py | POST /inbox drift drafts |
| mcp-scripts/playlive-hosts-loader.py | POST /inbox failover alert |
| board/kanban-commit.sh | renders handoff inbox on the served checkout before the git-add sweep |

Already-OK writers (no change needed): job-dispatcher.py,
wiki-talk-watch.py, netdata-nodes-watch.py, system-report-watchdog.py,
served-checkout-watchdog.py, host-ready-check.py, post-restart-verify.py,
lesson-drift-check.py — all already POST board-api /inbox.

## Verified

- `python3 -m py_compile` clean on all touched .py; `node --check` clean
  on all touched .mjs.
- `inbox_door.local_writes_ok`: exec→False, phantom chaba-tony-dell→False,
  dispatch worktree (unmarked)→True, /tmp→False.
- `render-handoff-inbox.py --dry-run` OK; board-api /health → 200.
- omen timers now covered: focus-dispatcher(.timer/.overnight),
  mcp-health-snapshot, mcp-link-monitor.service, audit-watchdog,
  devin-dispatch-watch (via render-handoff-inbox), gh-runs-watch,
  arp-inventory-scan, overnight-focus-review chain.

## Not done / follow-ups

- Existing litter untouched: exec checkout `~/CascadeProjects/chaba` still
  has ~106 dirty focus-inbox files; the non-git replica
  `~/CascadeProjects/chaba-tony-dell/docs/ssot/focus-inbox` on omen holds
  ~6327 files. Bulk deletion is destructive — left for a human/served-side
  cleanup decision (candidate: archive-then-delete like the 2026-11-14
  inbox-litter tarball).
- `/inbox` has no resolve/delete semantics — watchers that used
  delete-on-recovery (audit-watchdog, check-serve-config, ha-auth-watch
  existing_alert dedup) lose auto-resolve on non-served checkouts; they
  compensate with signature/state dedup where spam mattered.
- `scripts/ada/session-audit.py` writes to AUDIT_INBOX_DIR defaulting at
  the chaba-tony-dell path, but its unit isn't installed on omen (deployed
  copy at ~/.local/share/session-audit) — flagged, not guarded.
- `scripts/mcp_debug/focus.py` inbox→processed move + ssot.focus writes
  still assume a committable checkout (interactive MCP tool).

lessons:
- Non-git replica dirs defeat role-marker guards: `local_writes_ok` must
  treat "not a git worktree" as False, not "unmarked → allow".
- `/inbox` door has no dedup/resolve — porting file-writers that relied on
  same-filename rewrite or delete-on-recovery needs a signature state file
  or accepts standing items.
- `git rev-parse --absolute-git-dir` + `<gitdir>/chaba-role` is the cheap
  portable role check; works from .py and .mjs (execFileSync git).
- Dispatch worktrees are unmarked git worktrees → guards must allow them
  (they're committed by dispatch close-out machinery).
