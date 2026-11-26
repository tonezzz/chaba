---
category: troubleshooting
status: verified
created: 2026-11-26
source: auto-kb
---

# Verified root cause: when a served chaba checkout is left on

## What it is

- Verified root cause: when a served chaba checkout is left on a topic branch (e.g

## Context/Background

Created 2026-11-26 from automated KB creation workflow.

Additional context: 2026-11-26 idc03 served checkout recovery; ops-kanban-commit-guard and timer-alert-idc03-kanban-commit closed with evidence.

## Key Details

### Technical Details
- **Generated**: 2026-11-26
- **Source**: Automated KB creation skill
- **Category**: troubleshooting

### Implementation
- Verified root cause: when a served chaba checkout is left on a topic branch (e.g. land/*), scripts/board/kanban-commit.sh still runs `git push origin master`, which pushes the LOCAL master ref rather than HEAD. If that local master is stale, every tick fails non-fast-forward even though the current branch has all board commits and git-safe-pull reports "upstream already in HEAD"; pushing `origin HEAD:master` succeeds.
- Fix under the board lock: back up with `git bundle create /tmp/opencode/chaba-head-<ts>.bundle HEAD`, then `git branch -f master HEAD && git checkout master` (same commit, so no worktree churn), then one tick. Verify `git status -sb` shows no ahead/behind, `git ls-remote origin refs/heads/master` equals HEAD, and `systemctl --user show kanban-commit.service -p Result` is success. Observed 2026-11-26 on idc03: 35 commits stranded, fixed and two consecutive ticks succeeded.
- Prevention: keep served checkouts on master; when investigating repeated "push failed after 3 attempts", compare `git rev-parse master` against `git rev-parse HEAD` before blaming fetch/rebase.

## Related Documentation

- **[auto-chaba-creation.md](../../.windsurf/workflows/auto-chaba-creation.md)** - Automated KB creation workflow

## Tags

- **auto-generated**: Automatically created KB entry
- **2026**: Year tag
