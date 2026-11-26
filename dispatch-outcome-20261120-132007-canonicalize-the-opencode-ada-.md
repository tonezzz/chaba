# Dispatch outcome — canonicalize + publish the OpenCode-Ada command files

- card: `ada-opencode-command-publisher-20261108` (ADA-1224); scope answer: `narrow`
- branch: `dispatch/20261120-132007-canonicalize-the-opencode-ada-` — 1 commit, **not pushed** (dispatcher merge path)
- host: idc02 (dispatch worktree)

## What was found (live state, verified on idc02)

- The live command file `~/.local/share/ada-code/workspace/.opencode/commands/ada.md`
  (10,007 B, sha `29c878cc`) is the **pre-menu** version: the `/ada sweep`
  native-menu block ("Sweep Verdicts" `question` requirement) was added
  2026-11-08/09 and **silently removed by the ADA0186 live edit on
  2026-11-19**. `ada.md.bak-ADA0186-20261119-152809` still carries it —
  that content is now the canonical seed (10,790 B, sha `077aaff3`).
- `ada_mcp.py` (the ada-control bridge) is canonical in the **ada-voice**
  repo (`opencode/ada_mcp.py`, ff-synced to `~/CascadeProjects/ada-bridge`
  by `ada-ocb-bridge-sync.timer`); the workspace's own `.opencode/ada_mcp.py`
  is a stale unused copy. The Ada-side wrapper therefore belongs to
  ada-voice — specced in the runbook and carded (ADA-0016), not done here.
- Prior dispatch attempt left no diff/cause; this run reimplemented per
  the recorded card-comms design.

## What changed

| file | change |
|---|---|
| `stacks/idc02/ada-code/commands/ada.md` | canonical command file, sweep native-menu block restored |
| `scripts/board/opencode_command.py` | new — `COMMANDS` allowlist (name→fixed repo/deploy paths, size cap, required markers); ops `preview/validate/publish/sync/verify`; confirm+`expect_sha` gates; atomic deploy (local `tmp+rename`, or fixed-argv ssh `cat > tmp && mv -f`); post-landing sha verify; compact receipts |
| `scripts/board/board-api.py` | `/opencode-command` added to `REMOTE_WRITE_PATHS` (WP_LOCK serialization); `do_opencode_command` maps `PublishError`→`UpstreamError` and wires `_queue_commit` (commit worker → kanban-commit safe-pull+push — no new git plumbing) |
| `scripts/board/opencode-command.py` | new — Devin thin client; `--confirm` gate on mutations, `--via local` for host-side runs |
| `tests/board/test_opencode_command.py` | new — 24 tests: validation/markers, confirm+sha gates, idempotent publish/sync, atomicity (no `.new-*` left), fixed ssh argv + stdin piping, door commit-hook + error mapping |
| `scripts/board/opencode_command_bench.py` + `docs/reports/opencode-command-bench-2026-11-20.{md,json}` | real-fixture bench, both lanes on identical tmp state |
| `docs/kb/opencode-command-publisher.md` | runbook: ops contract, Ada wrapper spec (drop-in code), activation checklist |
| `docs/kb/board-api-write-door.md` | endpoint table row |
| `docs/ssot/jobs/ada/2026-11-20-opencode-command-publisher.yml` | job record |
| `docs/ssot/ssot.token-tools.yml` | catalog entry with measured savings |

## Token measurement (no savings claimed without data)

`opencode_command_bench.py` runs the real manual shell pipeline and the
real `handle()` ops against the real canonical+deployed files:

| scenario | manual | tool | Δ |
|---|---|---|---|
| publish-update | 8 calls, 11,904 B ingested | 5 calls, 2,335 B resp | 80.4% bytes, 74.4% tok-est |
| drift-repair | 6 calls, 11,839 B | 3 calls, 2,790 B | 76.4% bytes, 73.6% tok-est |

Both lanes verified the same end state (evidence equal). Authoring the
~10.8 KB candidate is identical in both lanes and excluded; the publish
request carries it once as output. The durable win beyond bytes: drift
like the ADA0186 loss becomes a hard `expect_sha`/marker error instead
of silent state.

## How to verify

- `python3 -m pytest tests/board/test_opencode_command.py` — 24 passed.
- `python3 scripts/board/board-api.py --selftest` — ok.
- `python3 scripts/board/opencode-command.py preview --via local` on idc02 —
  shows the real drift diff (canonical `077aaff3` vs deployed `29c878cc`).
- Bench: `python3 scripts/board/opencode_command_bench.py` — evidence equal.
- Suite: `tests/board` 166 passed; 1 pre-existing failure
  (`test_control_pane_projection` — live card fixture expects `doing`,
  now `done`; unrelated drift, not from this change).

## Remaining gates (deliberately not done)

1. `systemctl --user restart chaba-board-api` on idc03 post-merge —
   endpoint inert until the service reloads.
2. First real `sync --confirm` → deploys menu-restored ada.md to the idc02
   workspace (production surface; needs idc03→idc02 BatchMode ssh for the
   board-api user — sync reports UpstreamError honestly if absent).
3. ada-voice MCP wrapper `ada_command_publish` — card
   `ada-voice-ada-command-publish-mcp-tool-f-949f50` (ADA-0016), spec +
   code in the runbook; then `/ada publish-command` section in canonical
   ada.md via the door itself.

lessons:
- board-api sibling modules load via `sys.path.insert(parent)` — a plain
  `import opencode_command` resolves; tests that inject a separate
  module instance must also patch `api.opc.COMMANDS` for door tests.
- The ada-code workspace loads `ada_mcp.py` from the ada-voice ff-only
  worktree (`~/CascadeProjects/ada-bridge`), not its own `.opencode/`
  copy — Ada-side tool changes belong to repo ada-voice, not chaba.
- Live `.opencode/commands/ada.md` edits leave only `*.bak-<CARD>-<ts>`
  backups; a `before-<change>-<date>.md` sibling backup may hold the OLD
  content while an `.bak` holds the NEW — verify direction with diff,
  not filename.
- `sync`'s `expect_sha` is checked against the CURRENT canonical sha —
  pass the sha returned by `publish`, not the earlier `preview` value.
- On idc02, `ssh idc02` (self-alias) is publickey-denied — the
  publisher's local mode (hostname match) covers on-host runs; remote
  ssh only needs to work board-host→deploy-host.
