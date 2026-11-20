# Dispatch outcome — ada-opencode-command-publisher-20261108 (ADA-1224)

Session: `devin-task-20261121-061014-canonicalize-the-opencode-ada-` on tony-omen.
Branch: `dispatch/20261121-061014-canonicalize-the-opencode-ada-`.

## What happened

This is the third dispatch on this card. The real work was already
landed on `origin/dispatch/20261120-132007` (idc02 run, commit
`325a5f1acc`) and was verified + merged locally by the
`20261120-205550` run — which then died with `exit-code` before
checkpointing, so nothing reached origin and the card re-queued.

This run:

1. **Recovered the deliverable** — cherry-picked `325a5f1acc` onto
   current master (`2b65999444`) cleanly as `b7fcb0be65`: 12 files,
   +1784. (Skipped the old outcome/checkpoint commits — this session
   writes its own.)
2. **Re-verified** — `tests/board/test_opencode_command.py`: 24/24
   green; `board-api.py`, `opencode-command.py`,
   `opencode_command_bench.py` all compile.
3. **Closed the loop the dead run left open** — exercised the tool
   end-to-end against live state:
   - `verify --via local`: canonical `077aaff3` vs deployed `29c878cc`
     (pre-menu regression from the ADA0186 live edit) → out of sync.
   - `preview --via local`: diff is exactly the missing `/ada sweep`
     native-menu block — canonical is strictly deployed + the restored
     `question`-tool requirement.
   - Snapshot of the pre-sync deployed bytes saved to
     `$TASK_DIR/deployed-ada-29c878cc.md` (rollback evidence; the file
     was previously live-edited with no versioned source).
   - `sync --confirm --via local --expect-sha 077aaff3…`:
     atomic ssh write to idc02, post-write sha verify →
     `match: true`, `deployed_sha = 077aaff3`.
   - The `/ada sweep` native-menu requirement is live on idc02 again.

## Deliverables (all in commit b7fcb0be65)

- `stacks/idc02/ada-code/commands/ada.md` — canonical, versioned
  command file (menu-restored).
- `scripts/board/opencode_command.py` — allowlist backend
  (`COMMANDS` registry; preview/validate/publish/sync/verify;
  confirm+expect_sha gates; required-marker validation incl.
  `/ada sweep`, `Sweep Verdicts`, `` `question` tool ``; atomic
  local/fixed-argv-ssh deploy; sha verify). No arbitrary paths,
  no caller shell/git.
- `scripts/board/board-api.py` — `POST /opencode-command` door under
  WP_LOCK; publish queues commits via `_queue_commit` → commit worker →
  kanban-commit safe-pull+push (existing writer pipeline).
- `scripts/board/opencode-command.py` — Devin thin CLI (`--via api` or
  `local`).
- `scripts/board/opencode_command_bench.py` +
  `docs/reports/opencode-command-bench-2026-11-20.{md,json}` —
  measured baseline: 74–80% fewer ingested bytes, 8→5 / 6→3 calls,
  evidence equal.
- `tests/board/test_opencode_command.py` — 24 tests.
- `docs/kb/opencode-command-publisher.md` — runbook incl. the Ada-side
  `ada_command_publish` MCP wrapper spec (follow-up in ada-voice).
- `docs/ssot/jobs/ada/2026-11-20-opencode-command-publisher.yml` +
  `docs/ssot/ssot.token-tools.yml` entry.

## Still open after merge

- **board-api restart on idc03** — the `/opencode-command` endpoint is
  inert until the service reloads `board-api.py` post-merge.
- **Ada-side MCP wrapper** — spec is in the runbook; implementation is
  a follow-up card in `tonezzz/ada-voice` (`ada_mcp.py` is canonical
  there, ff-synced to idc02 by `ada-ocb-bridge-sync.timer`).
- Deployed file on idc02 is already synced (this run) — first post-merge
  `verify` through the live endpoint should return `match: true`.

## How to verify

```bash
python3 -m pytest tests/board/test_opencode_command.py -q   # 24 passed
python3 scripts/board/opencode-command.py verify --via local  # match:true
# post-merge + idc03 board-api restart:
curl -s https://idc03.taila0626a.ts.net:10000/opencode-command \
  -d '{"op":"verify","name":"ada","from":"devin"}' \
  -H 'Content-Type: application/json'   # expect "match": true
```

Rollback if ever needed: redeploy the bytes saved at
`$TASK_DIR/deployed-ada-29c878cc.md` via
`POST /opencode-command {op:"publish", confirm:true, …}` then `sync`.

lessons:
- Dispatch branches left unpushed when the unit dies mid-run are
  still recoverable locally via `git log <branch>` on the same host —
  cherry-pick the work commit, skip old outcome/checkpoint commits.
- The dead 20261120-205550 run had already done merge+verify; this run
  only needed to re-land the same commit and finish the live sync.
- `--via local` sync from tony-omen reaches idc02 over BatchMode ssh —
  the deploy path works end-to-end without the board-api door (which is
  inert until idc03 restart post-merge).
