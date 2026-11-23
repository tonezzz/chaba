# dispatch-outcome 20261123-105251-canonicalize-the-opencode-ada-

- card: ada-opencode-command-publisher-20261108 (ADA-1224)
- branch: dispatch/20261123-105251-canonicalize-the-opencode-ada-
- commit: aa7009fb40 — "opencode-command: narrow allowlisted publisher
  for ada-code command files" (single squashed commit on origin/master
  @ 778903e435; linear landing per repo convention)

## What this run did

The deliverable was already built and live-verified three times
(dispatches 20261120-132007 on idc02, 20261121-061014 on tony-omen,
20261121-062509 on tony-macbook), but every merge was lost — worktree
GC claimed the merge commits before they could be swept, and the
runner units exited non-zero after the sessions reported DONE. The
only durable copy was the pushed source branch
`origin/dispatch/20261120-132007-canonicalize-the-opencode-ada-`
(3 commits, 14 files).

This run landed that work durably:

1. Merged `origin/dispatch/20261120-132007` onto current master;
   resolved the recurring `docs/ssot/kanban/.render-state-board2`
   conflict keeping the master side (generated file — keeps the
   sweep merge clean).
2. Re-staged as ONE squashed commit (aa7009fb40) and rebased onto
   the 2 newer master commits — linear history, no merge commit to
   lose to GC again.

## Deliverable (all spec items)

- Canonical source: `stacks/idc02/ada-code/commands/ada.md`
  (10,790B, sha256 077aaff3…) — includes the `/ada sweep`
  native-menu block (`Sweep Verdicts` `question`-tool menu) that was
  silently lost in the ADA0186 live edit.
- Narrow shared tool: `scripts/board/opencode_command.py` (COMMANDS
  allowlist backend) behind board-api `POST /opencode-command`
  (`do_opencode_command`, WP_LOCK, `_queue_commit` writer pipeline)
  + Devin thin client `scripts/board/opencode-command.py`.
  Ops: preview / validate / publish / sync / verify.
- Safety: allowlisted command names only — no arbitrary paths, no
  caller shell/git. publish gated by confirm+expect_sha (previewed
  bytes == committed bytes); required-marker validation makes the
  sweep-menu block impossible to drop silently; sync is fixed-argv
  ssh, tmp+mv atomic, post-landing sha verify; commits ride the
  existing kanban-commit safe-pull+push pipeline.
- Token measurement: `docs/reports/opencode-command-bench-2026-11-20
  .{md,json}` + `scripts/board/opencode_command_bench.py` — real
  fixture, 5 reps/lane: publish-update 11.9KB→2.3KB response bytes
  (~74% token-est), drift-repair ~76%; evidence equal. No savings
  claimed beyond measured ingested bytes.
- Docs: `docs/kb/opencode-command-publisher.md` (runbook incl.
  ada-voice MCP wrapper spec — the Ada side is a follow-up in the
  ada-voice repo where ada_mcp.py is canonical),
  `docs/kb/board-api-write-door.md` row, `docs/ssot/ssot.token-tools
  .yml` entry, `docs/ssot/jobs/ada/2026-11-20-opencode-command
  -publisher.yml` job record.

## Live verification (this run, from tony-omen)

`opencode-command.py verify --via local` → ssh to idc02:
`canonical_sha == deployed_sha == 077aaff3… (10,790B), match: true`.
The deployed workspace file already carries the restored sweep menu
(manual post-ADA0186 fix confirmed by the 2026-11-21 runs); sync is
currently a no-op.

## Tests

- `pytest tests/board/test_opencode_command.py` — 24/24 passed
  (re-run post-rebase).
- Full `pytest tests/board/` — 848 passed; 3 failed, ALL the
  PRE-EXISTING live-data assertions in
  `test_control_pane_projection.py` expecting live card KNB-0229
  (`kanban-card-cycle-control-pane`) to be `column == doing` — it has
  moved to `done` on the live board and in the rendered
  `stacks/web/public/apps/board2/cards.json`. Neither file is touched
  by this change; same baseline failure prior dispatches recorded.
- `python3 -m py_compile scripts/board/board-api.py` — ok post-rebase.
- SSOT validation + optimization gates passed at commit.

## Not done / gates (unchanged from job record)

- board-api restart on idc03 post-merge — the /opencode-command
  endpoint is inert until chaba-board-api.service reloads.
- ada-voice MCP wrapper (`ada_command_publish` tool) — follow-up in
  tonezzz/ada-voice; spec is in the runbook.

## How to verify

```
python3 scripts/board/opencode-command.py verify --via local
python3 -m pytest tests/board/test_opencode_command.py -q
grep -n "Sweep Verdicts" stacks/idc02/ada-code/commands/ada.md
```

lessons:
- Merge commits made inside dispatch worktrees are fragile — worktree GC deletes them before merge-sweep lands them. Prefer pushing the dispatch branch (runner checkpoint does) or landing a squashed commit on the session branch.
- `.render-state-board2` conflicts on every merge of an aged dispatch branch — resolve with the master side; it is generated.
- `test_control_pane_projection.py::test_card_record_is_the_pane_card` is a live-data test that fails whenever KNB-0229 leaves `doing` — pre-existing baseline failure, not a regression signal.
- `git stash`/`stash pop` during an in-progress merge silently drops MERGE_HEAD — recover by staging everything and committing as a squashed change instead.
