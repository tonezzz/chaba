# Dispatch outcome — ada-opencode-command-publisher-20261108

- date: 2026-11-21
- host: tony-macbook
- branch: dispatch/20261121-062509-canonicalize-the-opencode-ada-
- head: merge commit bb97e0d6f2 + job-record update commit

## What this run actually did

This was a LANDING run, not new implementation. The deliverable was
already built and verified on `origin/dispatch/20261120-132007-...`
(3 commits, 14 files — pushed there by the idc02 run's dispatcher
checkpoint). A later run on tony-omen (dispatch/20261120-205550)
merged it locally as e86b46d6c9 and verified it, but that session
exited nonzero before the runner checkpoint could push, and the
worktree was GC'd — the merge was lost. Same story for
dispatch/20261117-233712.

This run re-did the merge on top of current master and left it
committed so the dispatcher checkpoint + merge-sweep can land it:

- `git merge origin/dispatch/20261120-132007-...` — one conflict,
  `docs/ssot/kanban/.render-state-board2` (generated hash file),
  resolved by keeping master's version. Chosen deliberately: keeping
  base means the eventual sweep merge is trivially clean (my side ==
  merge base → auto-takes whatever master has then).
- Auto-merged files inspected by hand — `board-api.py` grew ~2200
  lines on master since the branch's base; verified the import,
  REMOTE_WRITE_PATHS entry, do_opencode_command, and the routing
  branch all landed correctly. Syntax check passes.
- Committed as bb97e0d6f2 (pre-commit hooks: SSOT validation +
  optimization gate both passed).
- Updated the job record's stale lines (branch now on origin; the
  "first real sync" gate is obsolete — see below).

## The deliverable (spec items)

- Canonical command source: `stacks/idc02/ada-code/commands/ada.md`
  (165 lines, sha256 077aaff3) — includes the `/ada sweep` native-menu
  requirement (`Sweep Verdicts` question-tool block, the text that was
  silently lost in the ADA0186 live edit).
- `scripts/board/opencode_command.py` — name-locked COMMANDS
  allowlist; ops preview / validate / publish / sync / verify;
  confirm + expect_sha gates on every mutation; atomic tmp+mv deploy
  over fixed-argv ssh; bounded diffs; compact receipts. No arbitrary
  paths, no caller shell/git.
- `scripts/board/board-api.py` — `/opencode-command` door under
  REMOTE_WRITE_PATHS (WP_LOCK), PublishError → UpstreamError, commit
  hook → `_queue_commit` → kanban-commit safe-pull+push.
- `scripts/board/opencode-command.py` — Devin thin client (same door,
  `--via local` for host-side runs).
- Ada side: the door is the shared tool; the ada-voice MCP wrapper
  (`ada_command_publish`) is a carded follow-up in tonezzz/ada-voice
  where `ada_mcp.py` is canonical.
- `tests/board/test_opencode_command.py` — 24 tests, all pass here.
- Token measurement: `docs/reports/opencode-command-bench-2026-11-20.{md,json}`
  — real fixture, 5 reps/lane: publish-update 8→5 calls, 11.9KB→2.3KB
  response bytes (~74% tok-est); drift-repair 6→3 calls (~76-80%
  ingested bytes). Measured, not claimed.

## Live verification done from this worktree

- `ssh idc02 sha256sum .../ada-code/workspace/.opencode/commands/ada.md`
  = `077aaff3` — IDENTICAL to canonical. The menu-restored file is
  already deployed (manual fix post-ADA0186); `/ada sweep` and
  `Sweep Verdicts` confirmed present in the live file;
  `ada-code.service` is active.
- `POST /opencode-command` on live board-api → `{"error":"not found"}`
  as expected — the endpoint activates only after chaba-board-api
  restarts on idc03 post-merge (documented gate in the runbook).

## What remains after merge (handoff)

1. Merge-sweep lands this branch to master (clean — conflict already
   resolved; my render-state side equals the merge base).
2. Restart `chaba-board-api.service` on idc03 to activate the door.
3. Exercise the door once live (`verify` op — expected:
   `in_sync: true`, `077aaff3`).
4. Ada-voice MCP wrapper follow-up card (already filed).

## Verification

- `python3 tests/board/test_opencode_command.py` → 24 tests OK.
- `python3 -c "import ast; ast.parse(open('scripts/board/board-api.py').read())"` → OK.
- `git log --oneline origin/master..HEAD` shows merge bb97e0d6f2 +
  job-record commit carrying all 14 deliverable files.
- idc02 deployed hash == canonical hash (077aaff3), service active.

lessons:
- The repeated failure on this card was never the code — it was the
  handoff: merges committed locally but never pushed before worktree
  GC. A clean (exit-0) session end is what triggers the dispatcher
  checkpoint push + merge-sweep; a nonzero exit loses everything.
- `python3 -m unittest discover -s tests/board` went CPU-bound (97%,
  18+ min) on tony-macbook and writes side-effect files into the
  worktree (.render-state-board2, ssot.dev-system.assessment.yml) —
  run the targeted test file instead; restore generated files before
  finishing.
- `.render-state-board2` conflicts on every board-touching merge —
  resolve by keeping master's version; it also makes the downstream
  sweep merge conflict-free.
- Don't assume live state matches the last report: the deployed
  ada.md was re-verified and is already in sync, making the recorded
  "first sync" gate obsolete.
