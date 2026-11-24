# dispatch-outcome — dispatch-worktree-merged-triage (attempt 3)

Host: idc02 (runner claimed here; card text targeted tony-dell — both fleets swept, tony-dell via ssh).

## Result

All `dispatch-wt-*` worktrees on idc02 and tony-dell classified and swept. 23 of 24 zombies dropped; the 3 live worktrees (2 tony-dell reruns + this session) untouched. Every drop kept its local branch ref, so unpushed partial work remains reachable by branch name. Record-class salvage (outcome docs, jobs ymls, ada-engines spec) landed on this branch in `94f51a5410`; larger uncommitted deliverables were committed to their own dispatch branches before the worktree drop (`232247` → `213785ca`, `201723` → `408cb07c`, `195108` → `bb3734ec`). Full matrix: `docs/ssot/jobs/kanban/2026-11-23-dispatch-worktree-triage.yml`.

## Classification summary

- **merged-equivalent (6):** ada-voice 113415 (HEAD in origin/main), idc02 211038/211214/211338 (empty rate-limit deaths), tony-dell feat/card-run-lifecycle (cherry=0, upstream f7b7c83), 203754 (empty), knb-0013-queue-truth (clean manual wt).
- **abandoned-partial (14):** real unmerged work — all branch refs kept, shas recorded in the jobs yml + card comms. Highlights: completed arbiter label-pass (57b4500e, 6.5k lines), cline-review-feed (34b41338, 509L script), consultant-bench staged deliverable (→213785ca), control-pane run-evidence (51f4c829), board-api compact-cards (e2a860e6), gesture-rebuild on ada-voice (5307864b), wiki-page-door Infrastructure-prefix commit (c039ad5f — merge held by test-gate timeout on its card).
- **superseded (2):** both two-part-deliverable iterations (fleet-jobs card done via dispatch/20261121-164519) — older staged iteration preserved at 408cb07c anyway.
- **live-partial (3):** 144258 cms-publish + 144943 cline on tony-dell (in-flight reruns), this session on idc02 — hands off.

## Prior failure mode fixed

Attempts 1-2 died on provider rate-limits (retryable signature in run logs), not logic. This run completed the full sweep in-session. One structural note: the arbiter rerun on tony-omen is rebuilding 6.5k lines of work that exists only as an *unpushed local branch* on idc02 — recorded on the card so the work is findable; pushing salvage branches remains outside dispatch rules.

## Verify

- `git worktree list` in ~/CascadeProjects/chaba (idc02) → only this session's worktree.
- tony-dell `ls ~/CascadeProjects/dispatch-wt-*` → only 144258 + 144943 live runs.
- Salvage: `git show --stat 94f51a5410` (this branch); `git log dispatch/20261117-232247-*` on tony-dell → 213785ca.

lessons:
- Dispatch worktrees share one dirty harness-artifact file per host (idc02: a stale card yml; tony-dell: ssot.dev-system.assessment.yml) — identical across all worktrees, ignore for classification.
- devin-dispatch task meta at ~/.local/share/devin-dispatch/tasks/<slug>/meta.json maps worktree→card; prompt.txt has the card id when meta.card is null.
- Abandoned-partial work on *unpushed local* branches is invisible to reruns on other hosts — tony-omen rebuilt arbiter work that existed only on idc02. Push-or-record early.
- `git cherry` marks checkpoint-merge heads as unmerged even when content landed — check patch-equivalence per commit, not ahead-count.
