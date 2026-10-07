# dispatch outcome — dispatch-auto-merge

**Result: done.** The dispatch lifecycle now has a real close-out merge
step on both execution paths.

## What the card asked

Card `dispatch-auto-merge`: sessions finish real work but never merge —
4 cards rescued by hand in one evening (one committed on tony-omen and
never pushed). Add: enforced session-end checkpoint commit, always-push
of the dispatch branch, expected_goals gate, then merge --no-ff into
origin/<default> via safe-pull conflict conventions. Conflicts hold the
card in review; no-op runs skip silently.

## What changed

- `scripts/board/dispatch_repos.py` — new `close_out()` pipeline:
  `checkpoint()` (add -A + commit leftovers), `push_branch()` (always,
  before merge), `goals_gate()` (scripts/lib/goals.py executor in the
  worktree), `_merge_in()` rewritten to `--no-ff` + conflict policy
  (`SAFE_PULL_GENERATED_RE` paths → ours/upstream-wins,
  `dispatch-outcome*.md` → theirs/session-wins, anything else aborts and
  reports the path list), and `close_out_notes()` — the shared comms
  formatter. `try_merge()` kept as a shim.
- `scripts/board/kanban-dispatch.py` — phase B (`merge_pending_one`)
  calls `close_out`; stamps `action.verified` (True merged, False
  conflicts/held goals).
- `scripts/board/runner-agent.py` — remote claims run `close_out_merge`
  locally before posting finish; `dispatch_repos` is imported from
  `DISPATCH_REPOS_DIR`, the agent's own dir, or
  `~/CascadeProjects/chaba/scripts/board`; the merge's `verified` flag
  rides the finish body, comms notes post after.
- `scripts/board/board-api.py` — `do_finish` accepts `verified:bool`.
- `docs/ssot/kanban/ssot.kanban.yml` — new `execution.close_out` section
  + `verified` field and `do=finish` body docs.
- `docs/ssot/jobs/kanban/2026-10-07-dispatch-auto-merge.yml` — job record
  (design, deviations, deployment notes).
- `tests/board/test_dispatch_close_out.py` — 8 e2e cases, all pass.

## Noted deviations / flags

- Spec asked for `--no-ff`; chaba memory says "linear history, no merge
  commits". Card spec wins — merge commits mark dispatch provenance.
- The card's own `expected_goals` entry is malformed for goals.py
  (`check: "grep -q …"` needs a `command` prefix; the separate `expect:`
  key is dead config). Posted to comms — would hold the merge as-is.
- This card can't auto-merge itself — the runner-agent copy on tony-omen
  (`~/.local/bin/runner-agent`) predates the change (bootstrap).

## How to verify

```bash
python3 -m unittest tests.board.test_dispatch_close_out   # 8/8
python3 -m py_compile scripts/board/{dispatch_repos,kanban-dispatch,runner-agent,board-api}.py
```

Deployment: kanban-dispatch/board-api pick this up via chaba-tony-dell's
next pull; `~/.local/bin/runner-agent` on remote hosts is a manual copy —
re-copy from `scripts/board/runner-agent.py` after merge (until then,
remote cards get a "dispatch_repos module not found" comms line instead
of a merge).
