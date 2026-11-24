# Dispatch outcome — ops-1036: Dispatch worktree GC

Session: `dispatch-wt-20261124-193310-idc02-has-68-stale-dispatch-wt` (ran on tony-dell)
Card: `docs/ssot/kanban/cards/ops-1036.yml`

## What I found

The card asked for a bounded sweeper, but **the sweeper already existed**:
`scripts/board/dispatch-wt-sweep.py` shipped Nov 3 (e9a01ec68de + 06246073a29)
with all the required gates — forensic window, in-flight unit check, evidence
check, dry-run default — plus salvage-before-reap (69569e2b163 pushes unpushed
heads to `wip/dispatch/<tid>` and logs to card comms). What was missing:

1. **Nothing scheduled it.** No unit, no timer, no caller — it only ran when
   invoked by hand.
2. **`unit_active()` was systemd-only.** On macOS (kk-mac runs launchd) it
   would have kept-or-reaped blind.
3. **Evidence gate was narrower than what dispatch actually writes**
   (only events.jsonl/usage.json originally; meta.json/verdict.json/exit_code
   also prove a run happened).
4. **`git fetch --prune origin` ran once per worktree** — N stale trees on one
   repo meant N fetches (or N timeouts on a dead origin).

## What changed

**`scripts/board/dispatch-wt-sweep.py`**
- `unit_active()` → runtime-aware: darwin probes `launchctl print
  gui/<uid>/devin-task-<tid>` (base + `-fuN` followup plists under
  `~/.local/share/runner-agent/launchd/`); no launchctl → keep (keep-on-doubt).
- `on_origin()` dedupes the fetch once per repo root per sweep (`fetched` set).
- `EVIDENCE_FILES = (meta.json, events.jsonl, usage.json, verdict.json,
  exit_code)`.
- `DISPATCH_WT_SWEEP=0` kill switch inside `sweep()`.

**`scripts/board/runner-agent.py`** — the scheduled path (card's "declared
unit if periodic" satisfied with zero new units: runner-agent.timer /
LaunchAgent `ai.chaba.runner-agent` is already declared fleet-wide in
`ssot.audit.hosts.yml`):
- `wt_sweep_module()` — SourceFileLoader resolver (same convention as
  `lg_module`) for the hyphenated script.
- `wt_sweep_pass()` — runs `sweep(~/CascadeProjects, RUNNER_WT_SWEEP_DAYS=3,
  apply=True)` once per `RUNNER_WT_SWEEP_S` (default 86400s), throttled by
  `STATE_DIR/wt-sweep.ts`; warn-only, never raises, stamps even on failure.
- Called in `main()` after `verdict_pass(st)`; env knobs documented in header.

**Tests**: `tests/board/test_dispatch_wt_sweep.py` — 14 tests covering
evidence breadth, fetch-once-per-repo (real tmpdir worktrees), launchd
active/inactive/fuN-plist/no-launchctl, and the pass throttle/disable/
module-missing/failure-warn paths.

**Trail**: `docs/ssot/jobs/board/2026-11-24-dispatch-wt-sweep-schedule.yml`.

## Result / verification

- `pytest tests/board/test_dispatch_wt_sweep.py` — 14/14 pass.
- Related suites (`test_dispatch_runner_resilience`, `test_worktree_gc`,
  `test_runner_stale_worktree`) — 45 pass.
- Dry-run on this host (`--days 3`): all 41 local `dispatch-wt-*` correctly
  KEEP — every one is inside the forensic window (fleet dispatch cadence is
  high; trees churn before they age out). Gates verified earlier with
  `--days 0`: in-flight units KEPT, no-evidence KEPT, unpushed heads flagged
  for salvage-push.
- Deploy: no manual step — runner-agent `_self_update()` picks up the repo
  copy via chaba-repo-sync, and `wt_sweep_module()` resolves the sweep script
  from the same synced checkout. First sweep fires ≤24h after each host's
  runner-agent updates.

## Notes

- The two script edits were swept into the session's auto compaction commit
  (48cdb7a8480); the test file, job doc, and this outcome doc are the follow-up
  commit on the dispatch branch.
- Pre-existing unrelated failure: `test_control_pane_projection.py::
test_card_record_is_the_pane_card` — the test reads
`kanban-card-cycle-control-pane.yml`, which was archived upstream; fails on
clean HEAD too. Flagged on the card; not fixed here (out of scope).
- idc02's original 68-tree leak: this session ran on tony-dell; the sweeper is
  host-local by design, so idc02's trees get reaped once its runner-agent
  picks up the change — no idc02-side action needed.

lessons:
- The bounded reaper for OPS-1036 already existed (Nov 3) — check `git log`/`rg` for prior art before building; the real gap was scheduling, not the sweeper.
- Devin CLI compaction auto-commits the working tree under a "Compaction summary" message — uncommitted work is preserved but with a misleading commit message; check `git status`/`git show HEAD` after a compaction before assuming changes are uncommitted.
- `unit_active()`-style liveness probes must be runtime-aware: systemd-only checks silently mis-fire on launchd hosts (kk-mac); keep-on-doubt (return active when the probe tool is missing) is the safe default for reapers.
- Per-item `git fetch` inside a loop over N worktrees of one repo is a hidden O(N) network cost — dedupe by repo root.
- "Declared unit if periodic" does not require a NEW unit — riding an already-declared fleet timer (runner-agent) satisfies host-hygiene and covers every runner host incl. launchd.
