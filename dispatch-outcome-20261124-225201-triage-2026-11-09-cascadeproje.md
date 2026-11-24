# dispatch-outcome — dispatch-worktree-merged-triage (attempt 2, rerun)

Host: idc02 (card targets tony-dell fleet — swept via ssh, same as the
11-23 run). Prior failures were provider rate-limits/exit-code, not
logic; the 11-23 run had already dropped the original 16 worktrees, so
this run swept the *current* tony-dell fleet: 48 `dispatch-wt-*` dirs
(2026-11-23/24 vintage, chaba + ada-voice).

## Result

All 48 worktrees classified, salvaged where needed, and removed —
`ls ~/CascadeProjects/dispatch-wt-*` on tony-dell now returns 0 across
all 5 dispatch repos. Every `dispatch/*` branch kept as a local ref
(68 chaba + 13 ada-voice) so nothing is unreachable. 13 worktrees held
unique *uncommitted* state — each was committed onto its own dispatch
branch (`triage salvage: uncommitted worktree state snapshot`) before
the drop. The stranded 11-23 triage branch
(`origin/dispatch/20261123-144247-...`, never merged because the card
was held) had 17 record files absent from master — landed on this
branch. Full matrix:
`docs/ssot/jobs/kanban/2026-11-24-dispatch-worktree-triage-rerun.yml`.

## Classification summary

- **merged-equivalent (40):** branch HEAD ancestor of origin/<default>.
- **content-landed-equivalent (8):** not ancestors, but every card is
  done and the content verifiably landed via sibling reruns or
  alternate impls — verified by added-line-presence checks, not just
  git cherry (which marks all checkpoint merges unmerged).
- **live-partial (0 at end):** the one running unit (cf-ssl 222656)
  finished mid-run — ssl=strict verified live by the session itself —
  then its worktree was noise-reset and dropped too.
- **salvage-commits (13):** notable — runner-per-executor-caps staged
  delta (REMOTE_CAP pool split + 292L test file, never committed; the
  merged HEAD lacked it — flagged on the card), ada-voice wp_write.py
  37KB + backend mods, session-recall.py 13KB (absent on master),
  bank-inspect.py divergent variant, kkmac-classes bench corpus,
  stick-find.sh, plus outcome/jobs docs.

## Prior failure mode

Same as before: attempts died on provider rate-limits / exit-code, not
logic. Nothing in this run repeated a failed approach — the sweep is
read-only classify → commit-on-own-branch → `git worktree remove`
(no --force anywhere).

## Verify

- `ssh tony-dell 'ls -d ~/CascadeProjects/dispatch-wt-*'` → empty.
- `ssh tony-dell 'cd ~/CascadeProjects/chaba && git worktree list | grep -c dispatch-wt'` → 0.
- Salvage refs: `git -C ~/CascadeProjects/chaba log --oneline -1 dispatch/20261124-211725-problem-observed-2026-11-09-re` on tony-dell → `triage salvage: ...` commit.
- Stranded-branch landing: `git show --stat HEAD` on this branch includes the 17 files from `origin/dispatch/20261123-144247-...`.

lessons:
- `git worktree remove` on dispatch-wt dirs is safe ONLY after committing dirty state onto the branch first — uncommitted deliverables (staged cap-pool code, untracked scripts) die with the directory; the branch ref alone does not preserve them.
- `systemctl --user list-units devin-task-*` is the live-session source of truth, but a unit can finish mid-sweep — re-check before skipping, and treat "protected" as time-of-check only.
- The dirty file `docs/ssot/ssot.dev-system.assessment.yml` is harness noise (timestamp/score auto-bump) present in nearly every dead worktree — reset it, don't commit it; it alone defeats prune's clean-tree guard fleet-wide.
- `git cherry`/ahead-count lies for dispatch branches: "Devin checkpoint" merges and sibling reruns land content under different patch-ids — verify by grepping added lines against the master blob.
- A held card strands its dispatch branch forever (merge-sweep only handles doing/review) — rerun cards should merge the previous attempt's branch forward, like this run did.
