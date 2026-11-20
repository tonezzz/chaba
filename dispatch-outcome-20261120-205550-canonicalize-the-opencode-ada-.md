# Dispatch outcome — ada-opencode-command-publisher-20261108 (attempt: 20261120-205550, tony-omen)

## What this run did

Landed the previously-lost idc02 work per Tony's `merge-conflict` answer
("let devin resolve the conflict and land it"). `origin/dispatch/20261120-132007-canonicalize-the-opencode-ada-`
(3 commits: `325a5f1a`, `05d6be29`, `bdd2f99b`) was merged onto current
master as merge commit `e86b46d6c9` on this dispatch branch. The only
conflict was `docs/ssot/kanban/.render-state-board2` (generated render-state
hash) — resolved keeping master's newer hash. The tony-dell attempt's
earlier merge `947dd54` was lost with its GC'd worktree; this run redid
it identically.

## Deliverables verified in this worktree (14 files from the merged branch)

- `stacks/idc02/ada-code/commands/ada.md` — canonical command file
  (10,790B, sha `077aaff3`), seeded from `.bak-ADA0186` with the
  `/ada sweep` native-menu block restored.
- `scripts/board/opencode_command.py` — allowlist publisher: `preview /
  validate / publish / sync / verify`; fixed `COMMANDS` registry
  (name `ada` only), no arbitrary paths, no caller shell/git; confirm +
  `expect_sha` gates; fixed-argv ssh + tmp/mv atomic deploy + sha verify.
- `scripts/board/board-api.py` — `POST /opencode-command` door under
  WP_LOCK; publish rides `_queue_commit` → kanban-commit safe-pull+push.
- `scripts/board/opencode-command.py` — Devin thin client (HTTP default,
  `--via local` for host-side).
- `tests/board/test_opencode_command.py` — **24 tests pass**; all touched
  files py_compile clean.
- `scripts/board/opencode_command_bench.py` + `docs/reports/opencode-command-bench-2026-11-20.{md,json}`
  — measured vs manual shell baseline (5 reps, real fixtures):
  publish-update 8→5 calls, 11.9KB→2.3KB ingested (**~74% token-est ↓**);
  drift-repair 6→3 calls (**~76% ↓**). Honest accounting: publish request
  still carries the ~11KB candidate once.
- `docs/kb/opencode-command-publisher.md` — runbook + activation checklist.
- `docs/ssot/jobs/ada/2026-11-20-opencode-command-publisher.yml` — job record.
- `docs/ssot/ssot.token-tools.yml` — AUD-1033 entry with measured savings.

## Live verification performed (read-only ops, this host)

- `verify` → `in_sync:false` — deployed on idc02 is still the pre-menu
  10,007B (sha `29c878cc`); canonical is `077aaff3`. Drift confirmed real.
- `preview` → bounded diff shows the only delta is the Sweep Verdicts
  native-`question` block. ssh + sha path works end-to-end from tony-omen.

## NOT done (activation — deploy steps left for post-merge)

1. Merge this branch to master (dispatcher sweep — conflict already resolved).
2. `systemctl --user restart chaba-board-api` on idc03 (endpoint is inert
   until the service reloads `board-api.py`).
3. `opencode-command.py sync --confirm` then `verify` → expect `match:true`.
   First sync through board-api keeps the audit trail (`--via local` skips it).
4. ada-voice follow-up: `ada_command_publish` MCP wrapper in `ada_mcp.py`
   (canonical in tonezzz/ada-voice; spec is in the runbook §Ada side).

## Result

Spec satisfied: canonical versioned source, narrow shared tool
(preview/validate/confirm/commit-push/sync/verify), no arbitrary
paths/shell/git, sweep native-menu enforced as required markers,
token usage measured against a real manual baseline.

lessons:
- Dispatch work committed-but-unpushed dies with the worktree GC; only origin branches survive — merge-sweep's "session_gone" note means check origin first.
- `.render-state-board2` conflicts are generated-file churn — resolve by keeping master's hash, never hand-merge.
- `opencode-command.py --via local verify|preview` are safe read-only live checks from any host with ssh to idc02; `sync`/`publish` stay gated for activation.
- The endpoint is inert until `chaba-board-api` restarts on idc03 — code merged ≠ door open.
