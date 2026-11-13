# Dispatch outcome — chore-tony-dell-worktree-sprawl (2026-11-13)

## Result
tony-dell `~/CascadeProjects/chaba` (role=exec) went from **24 linked worktrees to 2**, and **9 stale local branches were deleted**. All committed work is preserved (worktree removal never deletes branches); all non-regenerable uncommitted content was salvaged before any `--force` removal. No commits were made on tony-dell; the only commit is on this dispatch branch (lands via normal dispatch merge).

## Worktree audit table

| Worktree | Branch | Card / status | Dirty | Verdict |
|---|---|---|---|---|
| card-wt-knb-0065 | card/knb-0065 | card-runner-lifecycle-test (done), branch merged | lifecycle-test.md + .gitignore → salvaged + committed via this dispatch | REMOVED, branch deleted |
| chaba-ada-envelope | feat/ada-envelope-transitions | disjoint lineage | clean | REMOVED, branch kept |
| chaba-ada-ha-kanban-wt | fix/s0-jobs-target-idc02 | disjoint lineage | untracked board2/ (6.6M prototype) → salvaged | REMOVED --force, branch kept |
| chaba-deploy-gate | fix/lesson-translation-cache | disjoint lineage | clean | REMOVED, branch kept |
| chaba-devin-memory-adapter | feat/devin-memory-pointers | disjoint lineage | clean | REMOVED, branch kept |
| chaba-jack-cf-ada-gateway | feat/ada-access-auto-enroll | ada-bge-memory-search-shadow (doing) | 8 untracked BGE files, all differ from master versions → salvaged | REMOVED --force, branch kept |
| chaba-knb1257 | fix/knb-1257-request-field | board-cli-request-ask-field (backlog), 9 unlanded commits | regenerable assessment file | REMOVED, branch kept |
| chaba-opencode-tab | feat/ada-opencode-dashboard-tab | disjoint lineage | clean | REMOVED, branch kept |
| chaba-ops1255-review | fix/ops-1255-requalification | opencode-lane-regraduation (doing) — card comms name this dir as the review draft | regenerable assessment file | **KEPT** |
| chaba-pack-manifest | detached 7a687f6ffec | baseline-refresh commit, regenerable | clean | REMOVED (commit left unreachable by design) |
| chaba-private-news-wt | ops/private-news-lane | disjoint lineage | clean | REMOVED, branch kept |
| chaba-r7gpu | feat/r7-gpu-cap | disjoint lineage | clean | REMOVED, branch kept |
| chaba-reindex-fix | fix/mddb-reindex-retries | content landed (git cherry '-') | clean | REMOVED, branch deleted |
| chaba-rerank-svc | feat/bge-rerank-server | disjoint lineage | clean | REMOVED, branch kept |
| chaba-retry2 | fix/lessons-shadow-retry | disjoint lineage | clean | REMOVED, branch kept |
| chaba-rfix | fix/bge-rerank-unit | disjoint lineage | clean | REMOVED, branch kept |
| chaba-shadow-timeout | fix/education-shadow-timeout | disjoint lineage | clean | REMOVED, branch kept |
| ops1131-preview-wiring | fix/metno-rain-units | 1 of 2 commits landed; 1 unlanded docs commit | regenerable assessment file | REMOVED, branch kept |
| chaba-wt-devin-token-efficiency | dispatch/devin-token-efficiency | devin-ada-card-ops-efficiency (done), content landed | regenerable assessment file | REMOVED, branch deleted |
| chaba-wt-devin-token-efficiency-ready | feat/devin-ada-card-ops-efficiency | same card, content landed | clean | REMOVED, branch deleted |
| chaba-wt-memguard-verify | detached 0809ead3a3b | kk-mac-live-memory-guard (review), 1032-line feature commit, was orphaned | clean | commit pinned to new branch `fix/kk-mac-memory-guard`, then REMOVED |
| chaba-wt-ssot-service-inventory-drift | consult-bench | ada-consultant-bench-harness (done), content landed | regenerable assessment file | REMOVED, branch deleted |
| dispatch-wt-20261002-… | feat/card-run-lifecycle | active devin workspace | clean | **KEPT** |

## Branches deleted (9)
- Ancestor-merged (`git branch -d`): card/knb-0065, nest-health-kk, dispatch/mddb-embed-free-first, ops-embed-relocate, ops-mn01-embed-relocate
- Content-merged, verified via `git cherry origin/master` (all `-`): fix/mddb-reindex-retries, dispatch/devin-token-efficiency, feat/devin-ada-card-ops-efficiency, consult-bench

## Salvage
`tony-dell:~/CascadeProjects/worktree-salvage-20261113/` (6.6M): `knb-0065/` (lifecycle-test.md + gitignore.diff — also committed to this dispatch branch), `board2/` (untracked prototype), `jack-cf-bge/` (BGE script/pack variants differing from master).

## Ambiguous / needs follow-up (posted to card)
- ~13 surviving branches are on a **disjoint history lineage** — zero shared commits with origin/master, so `git branch --merged` can never verify them. They need a content-level audit (tree diff per changed file) before branch deletion; left intact.
- `~/CascadeProjects/chaba-tony-dell-worktrees/knb-0928-hands-off` is an **unregistered** checkout dir with a **live picker-server process** (running since Nov-08). Not touched.
- mn01's own `~/CascadeProjects/chaba` has similar dispatch-wt sprawl — same procedure applies if wanted.

## Committed in this dispatch worktree
- `reports/card-runner/lifecycle-test.md` + `.gitignore` exception (preserved knb-0065 artifacts)
- `docs/ssot/jobs/infrastructure/2026-11-13-tony-dell-worktree-sweep.yml` (job record)

## Verify
```
ssh tony-dell 'cd ~/CascadeProjects/chaba && git worktree list && git branch --merged origin/master'
# expect: 3 lines (master + ops1255-review + dispatch-wt …card-run-lifecycle); merged list = master only
```
