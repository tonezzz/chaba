# Dispatch outcome — ada_command_publish MCP tool (ADA-0016)

## What changed

Card `ada-voice-ada-command-publish-mcp-tool-f-949f50`: added the
`ada_command_publish` tool to `opencode/ada_mcp.py` and published the
`/ada publish-command` section into canonical `ada.md` through the
`/opencode-command` door itself.

### ada-voice repo (the actual deliverable)

The card's edit point is tony-dell `~/CascadeProjects/ada-voice`, but
this dispatch ran on tony-macbook. Following the established pattern, I
fetched `origin/main` and created a dedicated worktree (kept outside
this chaba worktree so the dispatcher cannot sweep the nested repo into
a chaba commit):

- Worktree: `/home/tony/CascadeProjects/ada-voice-wt-ada-command-publish`
- Branch: `dispatch/ada-command-publish-mcp-tool` (1 commit `20a39ad`
  ahead of `origin/main` a060335; **NOT pushed** — dispatch rails)

Commit `20a39ad` contains:

- `opencode/ada_mcp.py` — `ada_command_publish(operation, name="ada",
  content="", expect_sha="", confirmed=false)` verbatim per
  `docs/kb/opencode-command-publisher.md` "Ada side": thin
  `_post_json("/opencode-command", body)` wrapper, bad-op rejection,
  content/expect_sha passthrough, and the same two-call confirm gate as
  `ada_card_action` (unconfirmed publish/sync returns the door's
  `preview` op result with a `confirmed=true` warning; confirmed calls
  set `confirm: true`). `mutations` lists `publish`/`sync` only.
- `tests/test_opencode_ada_mcp_command_publish.py` — 6 unit tests
  (bad op, read-op passthrough, unconfirmed gate for publish AND sync,
  confirmed flag on the wire, error path).
- `docs/ssot/jobs/ada/2026-11-25-ada-command-publish-mcp.yml` — job
  trail with deploy notes.

### chaba repo (this worktree)

- `stacks/idc02/ada-code/commands/ada.md` — new
  `/ada publish-command <op> [name]` bullet documenting the tool's ops,
  the confirm gate, and the `expect_sha` rule. **Published to canonical
  via the door**: `scripts/board/opencode-command.py publish --confirm
  --expect-sha 3a639d23…` returned `ok:true, changed:true,
  commit:"queued"` — the served checkout on idc03 now carries the new
  canonical (sha `3a639d23`, 11,421B vs prior `077aaff3`, 10,790B) and
  the writer pipeline (kanban-commit safe-pull+push, ~15min cadence)
  will land it on origin/master. This is the door's first real use.
- The identical file edit is also committed on this dispatch branch so
  the worktree merge is consistent whichever lands first (identical
  content merges cleanly).

## Verification

- `pytest tests/test_opencode_ada_mcp_command_publish.py` — **6 passed**
- `pytest tests/ -k "opencode_ada_mcp or sync_ocb or ocb_eval or
  command_publish"` — **116 passed**
- `python3 scripts/tool-lint.py` — clean (69 warnings, none new)
- Door: `validate` → `valid:true, sha256 3a639d23…`; `publish` →
  `ok:true, commit queued`; `verify` → canonical `3a639d23`/11,421B,
  deployed still `077aaff3`/10,790B (`match:false` — expected, see
  below)

## Deliberately NOT done

- **No `sync` op.** The deployed idc02 command file still lacks the
  `/ada publish-command` section until `ada_command_publish` is live —
  syncing now would advertise a tool that does not exist yet. After the
  ada-voice branch merges and `ada-ocb-bridge-sync.timer` ff's
  `~/CascadeProjects/ada-bridge`, run
  `scripts/board/opencode-command.py sync --confirm` (optionally with
  `--expect-sha 3a639d23…`).
- No push/merge of the ada-voice branch — left for review on the
  tony-dell edit point.

## How to verify / next steps

1. Review/merge `dispatch/ada-command-publish-mcp-tool` in
   `~/CascadeProjects/ada-voice` (or push the branch to origin).
2. `ada-ocb-bridge-sync` ff's `~/CascadeProjects/ada-bridge` on idc02.
3. `scripts/board/opencode-command.py sync --confirm` → `verify` should
   return `match:true`.
4. In an ada-code opencode session, `/ada publish-command verify`
   should return the door receipt through the new MCP tool.

lessons:
- `opencode-command.py preview` ignores `--file` (canonical-vs-deployed
  only); use `validate --file` for candidate checks and pass
  `--expect-sha` from validate's `sha256` to publish.
- A venv from a sibling ada-voice worktree
  (`ada-voice-wt-*/.venv/bin/python`) runs this worktree's pytest fine —
  no need to rebuild one per dispatch worktree.
- Publishing canonical via the door writes on the idc03 served checkout
  and queues the commit; keeping the identical edit on the dispatch
  branch merges cleanly regardless of which lands first.
