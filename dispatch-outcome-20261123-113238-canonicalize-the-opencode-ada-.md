# dispatch-outcome — canonicalize-the-opencode-ada- (20261123-113238, idc02)

## What this session did

Verification-and-closeout run. The full deliverable was built on
2026-11-20 (dispatch/20261120-132007), lost to worktree-GC three times
as unmerged branches, re-landed twice today (105251 squash aa7009fb40,
105931 merge faa1864e67), and **auto-merged to origin/master at
2026-11-23 11:12 (68e53950)** — before this dispatch was claimed. This
session re-verified every spec item on the merged tree and cleared the
remaining live gates.

## Verified state (all on origin/master, re-checked this session)

- **Canonical source** — `stacks/idc02/ada-code/commands/ada.md`
  (10,790B, sha256 `077aaff3…`) carries the `/ada sweep` native-menu
  block: markers `/ada sweep`, `Sweep Verdicts`, `` `question` tool ``
  all present. The menu was silently lost in the ADA0186 live edit
  2026-11-19; it is now versioned AND enforced —
  `required_markers` in validation makes a menu-less candidate a hard
  error.
- **Narrow shared tool** — `scripts/board/opencode_command.py`: fixed
  `COMMANDS` allowlist (`ada` only), ops
  preview/validate/publish/sync/verify, `confirm:true` + `expect_sha`
  gates on every mutation, atomic tmp+mv deploy (local on idc02,
  fixed-argv ssh otherwise), post-landing sha verify. No arbitrary
  paths, no caller shell/git — publish commits ride board-api's
  `_queue_commit` → kanban-commit safe-pull+push (the writer pipeline).
- **board-api door** — `/opencode-command` wired at
  `do_opencode_command` (board-api.py:4394), in REMOTE_WRITE_PATHS
  (WP_LOCK), `PublishError → UpstreamError`, actor audit.
- **Devin client** — `scripts/board/opencode-command.py` thin CLI
  (all five ops, `--confirm`, `--via local`).
- **Live door check** — real `POST /opencode-command {op:verify}` to
  idc03 board-api returned `match:true, in_sync:true` — proves the
  service reload activation gate is cleared (runbook checklist 1-2).
- **Deployed hash** — direct sha256 on idc02 plus the live door both
  show deployed `~/.local/share/ada-code/workspace/.opencode/commands/ada.md`
  == canonical (`077aaff3…`); the first-real-sync gate resolved as a
  verified no-op (menu already live since the 2026-11-21 dispatch ran
  `sync --confirm`).
- **Tests** — `pytest tests/board/test_opencode_command.py`: 24/24
  green on merged master.
- **Measurement** — `docs/reports/opencode-command-bench-2026-11-20.{md,json}`:
  real-fixture bench, 5 reps/lane — publish-update 8→5 calls,
  11.9KB→2.3KB ingested bytes (~74% tok-est); drift-repair 6→3 calls
  (~76%). Authoring excluded both lanes; honest caveat recorded — no
  savings claimed without data.
- **Trail** — runbook `docs/kb/opencode-command-publisher.md`, endpoint
  row in `docs/kb/board-api-write-door.md`, job record
  `docs/ssot/jobs/ada/2026-11-20-opencode-command-publisher.yml`.

## Changes this session (2 files, docs only)

- `docs/kb/opencode-command-publisher.md` — Status flipped
  implemented→live; records the verified merge + live `verify` receipt.
- `docs/ssot/jobs/ada/2026-11-20-opencode-command-publisher.yml` —
  cleared gates moved to a `post_merge_verification` block (endpoint
  live, sync gate resolved, tests re-run); the two genuinely-open
  follow-ups stay in `not_done_gates`.

## Still open (tracked, out of this card's chaba scope)

- `ada_command_publish` MCP tool in ada-voice (`ada_mcp.py`) — follow-up
  card `ada-voice-ada-command-publish-mcp-tool-f-949f50` (backlog);
  exact implementation specced in the runbook's "Ada side" section.
- `/ada publish-command` section in canonical ada.md — after the
  wrapper lands (first real use of the door).

## How to verify

```bash
# via the live door (read-only)
curl -s -X POST https://idc03.taila0626a.ts.net:10000/opencode-command \
  -H 'Content-Type: application/json' \
  -d '{"op":"verify","name":"ada","from":"devin"}'   # => "match": true
# on idc02 directly
python3 scripts/board/opencode_command.py '{"op":"preview","name":"ada"}'
pytest tests/board/test_opencode_command.py -q      # 24 passed
```

lessons:
- Re-dispatched cards can arrive already-merged: check origin/master
  for the deliverable BEFORE rebuilding — this card's work was
  auto-merged 20min before the dispatch claim.
- DONE-then-exit-code failures on this card were runner bookkeeping
  races (worktree GC / rate-limit signature), not work failures — the
  comms trail + origin branches held the real state.
- `.render-state-board2` conflicts every merge — always resolve
  master-side; the sweep merge then lands clean.
- Verifying through the live door (real POST to board-api) clears the
  service-reload activation gate and the hash gate in one call.
