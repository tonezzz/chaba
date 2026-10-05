# Dispatch outcome — kanban-commit-conflict-marker-guard

## What changed

`scripts/board/kanban-commit.sh` now refuses to commit unsafe staged state instead
of silently writing conflict markers into git history:

- **Mid-operation gate** — refuses (before `git add`, so staging can't mark
  conflicts resolved) when `rebase-merge/`, `rebase-apply/`, `MERGE_HEAD`, or
  `CHERRY_PICK_HEAD` is present under `git rev-parse --git-dir`. This is the exact
  incident vector: the script's own `git pull --rebase` conflict leaves
  `<<<<<<<`/`=======`/`>>>>>>>` in card files; the next tick used to stage+commit
  them, and the poisoned YAML then crashed render-board + kanban-dispatch on parse.
- **Marker gate** — after staging, `git diff --cached --check`; any output line
  containing `conflict marker` (i.e. `file:line: leftover conflict marker`)
  refuses the commit and logs the `file:line` list to stderr (journal). Only
  newly-added marker lines flag — pre-existing markers at HEAD can't wedge the
  loop, and trailing-whitespace warnings do not block.
- **Board alert** — on refuse, upserts
  `docs/ssot/kanban/cards/ops-kanban-commit-guard.yml` (column `review`, note
  names the offending files) under the `/tmp/board-api.lock` flock — the
  sanctioned direct-write path. Deduped: a repeat hit with the same file set
  only bumps `updated` (no 15-min comms spam); a changed reason or a re-hit
  after close appends comms and re-opens. The card rides into git on the next
  healthy commit.

Trail doc: `docs/ssot/jobs/kanban/2026-10-05-kanban-commit-conflict-marker-guard.yml`.

## Result

Verified end-to-end in a scratch bare-remote+clone inside the worktree
(`KANBAN_REPO` pointed at it): clean run commits+pushes as before; planted
`<<<<<<<`/`=======`/`>>>>>>>` in a test card → exit 1, stderr names
`test-card.yml:{3,5,7}`, zero new commits, alert card created with the file
named in its note; repeat run dedupes; faked `rebase-merge/` refuses before
staging; after fixing markers the next run commits normally (alert card lands
in git); a trailing-whitespace file commits fine.

## How to verify

`KANBAN_REPO=<any clone> bash scripts/board/kanban-commit.sh` after planting a
marker in a file under `docs/ssot/kanban/` — expect exit 1, `REFUSING` stderr,
and `ops-kanban-commit-guard.yml` updated in that repo.

## Known gap (out of scope)

If markers are pushed to origin/master from another writer, render/dispatch
still crash on parse — a parse-tolerant loader in render-board.py /
kanban-dispatch.py is separate work. `kanban-sync.sh` reviewed: ff-only merge +
machine-generated files → no equivalent vector.
