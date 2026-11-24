# dispatch-outcome — audit-miss-ada-voice-job-records

## Task
Recover two `docs/ssot/jobs/ada/` records missing from ada-voice `origin/main`:
`2026-10-10-voice-session-churn-context-billing.yml` and
`2026-10-13-line-file-doc-ingest.yml`.

## What was found / done

- Verified both files absent from ada-voice `origin/main` (fetched; 135 commits
  behind local main did not matter — checked `origin/main` tree directly).
- **voice-session-churn-context-billing**: not on any reachable host's
  working tree, but recovered **verbatim** from the orphaned dispatch branch
  `dispatch/20261010-080544-ada-voice-sessions-churn-1-min` in idc03's
  `~/CascadeProjects/ada-voice` clone (`git show <branch>:<path>`). That branch
  was the merge-conflict orphan from the original 2026-10-10 churn dispatch
  (pwa_server.py conflict; worktree later GC'd but the branch survived).
- **line-file-doc-ingest**: identical copies in three chaba worktrees
  (`chaba-wt-cline-network-integration-20261028`,
  `chaba-wt-kk-mac-fast-submit-20261030`, and this dispatch worktree / chaba
  master) — `diff -q` clean across all three. Content still valid: it is a
  record of a staged-but-undeployed chaba-side drop
  (`integrations/ada-voice/...`), which matches its `status:
  shipped-chaba-pending-adapi`.
- Created ada-voice worktree
  `~/CascadeProjects/ada-voice-wt-audit-job-records-20261124` on branch
  `dispatch/20261124-220336-audit-miss-ada-job-records` off `origin/main`,
  committed both files, pushed branch to `origin` (ada-voice dispatch-branch
  flow; merge-sweep lands it on main — same mechanism the original churn
  branch used).

## Result

- ada-voice `origin/dispatch/20261124-220336-audit-job-records`… (branch:
  `dispatch/20261124-220336-audit-miss-ada-job-records`) contains both files
  at `docs/ssot/jobs/ada/`. They reach `main` via the normal ada-voice
  merge-sweep.
- Chaba worktree: no repo changes needed (deliverable is in ada-voice);
  card comms updated via board-api.

## Verify

```
cd ~/CascadeProjects/ada-voice && git fetch origin
 git ls-tree origin/dispatch/20261124-220336-audit-miss-ada-job-records \
   docs/ssot/jobs/ada/2026-10-10-voice-session-churn-context-billing.yml \
   docs/ssot/jobs/ada/2026-10-13-line-file-doc-ingest.yml
# after merge-sweep lands:
git ls-tree origin/main docs/ssot/jobs/ada/ | grep -E 'voice-session-churn|line-file-doc-ingest'
```

## Notes / caveats

- The churn record's `verification:` block is not strict YAML (plain scalars
  containing `: ` inside a block sequence) — kept verbatim as the authentic
  session artifact; ada-voice CI (`tool-lint`, scenario coverage) does not
  parse `docs/ssot/jobs/**`.
- The original churn fix itself (pwa_server.py conflict) was resolved
  separately per the archived `ada-voice-session-churn` card — this dispatch
  only recovered the job *record*.

lessons:
- Orphaned ada-voice dispatch branches survive worktree GC on the runner
  host — `git branch -a | grep <slug>` + `git show <branch>:<path>` on idc03
  recovers "lost" artifacts without needing session-history spelunking.
- `docs/ssot/jobs/ada/*` records are committed to BOTH chaba and ada-voice;
  an audit miss in one repo does not mean the file is gone — check stale
  chaba worktrees and orphan dispatch branches before recreating.
