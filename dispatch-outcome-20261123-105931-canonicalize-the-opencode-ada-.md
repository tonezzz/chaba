# dispatch-outcome — canonicalize-the-opencode-ada- (20261123-105931, idc02)

## What this session did

Landed the already-built, already-verified deliverable. Prior attempts
produced complete work on `origin/dispatch/20261120-132007` (3 commits,
14 files) but every landing attempt died post-DONE (worktree GC'd /
service exit-code), so the merge to master was repeatedly lost. This
session re-merged that exact branch onto current master and re-verified.

- Merged `bdd2f99b` (origin/dispatch/20261120-132007) onto master as
  `faa1864e67`; only conflict was `docs/ssot/kanban/.render-state-board2`
  — kept master-side, matching every prior resolution.
- Re-verified the full spec on the merged tree.

## Deliverable (from the recovered branch, unchanged)

- `stacks/idc02/ada-code/commands/ada.md` — canonical command file;
  `/ada sweep` native-menu block present (markers: `/ada sweep`,
  `Sweep Verdicts`, `` `question` tool ``), sha256 `077aaff3…`, 10,790B.
- `scripts/board/opencode_command.py` — narrow backend: fixed
  `COMMANDS` allowlist, ops preview/validate/publish/sync/verify,
  confirm+expect_sha gates, required-markers validation (the sweep
  block cannot silently drop again), atomic local+fixed-argv-ssh
  deploy, post-landing sha verify. No arbitrary paths, no caller
  shell/git — publish commits ride board-api's commit worker into
  kanban-commit safe-pull+push.
- `scripts/board/board-api.py` — `/opencode-command` door
  (`do_opencode_command`, route at L5314, REMOTE_WRITE_PATHS entry).
- `scripts/board/opencode-command.py` — Devin thin client
  (`--confirm` gate, `--via local`).
- `scripts/board/opencode_command_bench.py` +
  `docs/reports/opencode-command-bench-2026-11-20.{md,json}` —
  measured baseline: publish-update 8→5 calls, 11.9KB→2.3KB ingested
  bytes (~74% tok-est); drift-repair 6→3 calls (~76%). Authoring
  excluded both lanes; no savings claimed without this data.
- `tests/board/test_opencode_command.py` — 24 tests.
- `docs/kb/opencode-command-publisher.md` runbook; endpoint row in
  `docs/kb/board-api-write-door.md`; registry entry in
  `docs/ssot/ssot.token-tools.yml`; job record
  `docs/ssot/jobs/ada/2026-11-20-opencode-command-publisher.yml`.

## Verified this session (on idc02, the deploy host)

- `pytest tests/board/test_opencode_command.py` — 24 passed.
- All touched files compile clean.
- `verify --via local` live: canonical_sha == deployed_sha ==
  `077aaff3…` (10,790B) — `in_sync: true`.
- `validate --via local` — valid, 0 errors (required markers present).
- `sync --confirm --via local` — confirm gate works, correctly no-ops
  ("already in sync — nothing deployed"). This resolves the job
  record's "first real sync" not-done gate: deployed already matches
  canonical.
- `ada-code.service` active — live workspace serves the canonical
  bytes.
- Wider board suite: 67 passed / 4 failed, ALL failures are 5s
  urlopen timeouts on `/comment`+`/action` tests — server returned
  200 after client gave up; `save_ms` observed at 5–22s because idc02
  is at load ~26 on 4 cores. Environmental, unrelated to this diff
  (same tests are on unrelated endpoints).

## Post-merge gates (for the operator, not this worktree)

- Restart `chaba-board-api.service` on idc03 after merge — endpoint
  inert until reload.
- ada-voice MCP wrapper (`ada_command_publish`) — separate follow-up
  card; ada_mcp.py lives in tonezzz/ada-voice.
- `/ada publish-command` section in canonical ada.md — after the MCP
  wrapper lands.

## How to verify

```
pytest tests/board/test_opencode_command.py -q        # 24 passed
python3 scripts/board/opencode-command.py verify --via local   # on idc02: match:true
# or via the door after board-api restart:
python3 scripts/board/opencode-command.py verify      # in_sync: true
```

lessons:
- Card was already DONE 3x on origin/dispatch/20261120-132007; the repeating failure is landing, not building — re-merging the verified branch is the right move, don't rebuild.
- `.render-state-board2` conflicts on every merge of this branch — always resolve master-side.
- idc02 under load ~26/4 cores makes board-api save_ms hit 5-22s; 5s-timeout tests in test_board_api_reads/action_persistence fail environmentally — check save_ms in stderr before suspecting a regression.
- `sync --confirm --via local` on the deploy host is a safe end-to-end check — it no-ops when already in sync but still exercises the confirm gate.
