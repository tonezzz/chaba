# Dispatch outcome — idc03-vault-checkout-drift

Card: `idc03-vault-checkout-drift` — converge the live vault checkout at
`idc03:~/CascadeProjects/chaba-vault` (production ada-memory services run
from it; it was master ahead 1 / behind 4217 with 8 dirty tracked files).

## What was done

**(a) Dirty-file review — all take-origin.** The 5 named scripts
(`memory-distill`, `memory-gap-report`, `memory-health-check`,
`memory-staleness-sweep`, `recall-drift-report`) each replaced the
`ssh tony-dell chaba-event-log.py` emit with `import chaba_event` — a manual
backport of upstream `f1fa7c72`. Worktree versions were byte-identical to
origin except gap-report/staleness-sweep, which differed only by the stale
`100.74.146.0` mddb literal. Untracked `scripts/ada/chaba_event.py` was
byte-identical to the upstream-tracked file. Staged
`sync-ada-memory-to-mddb.py` (earlier surgical patch) and the two dirty
obsidian HTML files were also identical to origin. No intentional unmerged
local work found — nothing required keep-local.

**(b) Snapshot + merge.** Snapshotted first: `git stash push -m
"vault-local-mods snapshot 2026-10-07"`, durable branch
`wip/vault-mods-20261007` on the stash commit, plus
`~/vault-untracked-backup-20261007.tgz` of all 72 untracked paths. Removed
~33 untracked vault docs that were byte-identical to origin blobs (merge
collisions); kept ~38 local-only extract docs. `git merge origin/master`
completed **clean — zero conflicts**. Result: `master` ahead 3 / behind 0.

**(c) IP sweep.** Post-merge, 3 files still carried `100.74.146.0` under
`scripts/`/`apps/`; all rewritten to hostnames and committed on idc03 as
`db9af6d7`:
- `apps/obsidian/server.py` — MDDB default → `http://idc03.taila0626a.ts.net:11023/v1` (curl /health = 200)
- `scripts/mddb-binlog-canary.py` — follower alert text → `idc02:11023` / `idc01:11123`
- `scripts/ada/host-services-cms.py` — idc01 `"ip"` → `""` (hostname already in `"ts"`; matches idc02 convention)

Note: `100.74.146.0` is idc01's **real current** tailnet IP — only the mddb
pointers were stale; the idc01 host-record/alert references were correct
data, converted to hostnames per the card's durable-model directive.
The same 3-file fix is mirrored in this dispatch worktree (unpushed) so it
lands upstream on merge.

**(d) Regression check.** `ada-memory-sync.service` ran twice, exit 0, no
CONFLICT lines — the 5 vault-vs-voice conflicts are resolved (take-vault
decision already applied upstream). `ada-memory-gaps.service` exit 0
("0 misses, 0 gap drafts") — exercises the freshly-converged gap-report.

## Convergence state

- `git rev-list HEAD..origin/master` = **0** (goal: <100) ✓
- `grep -rl 100.74.146.0 scripts/ apps/` = **0** ✓
- `ada-memory-sync.service` exit 0 ✓
- Tracked-dirty files: 0. Untracked: ~38 local-only vault extract docs
  (new data, untouched — as before).

## Leftovers

- idc03 `master` is ahead 3 (inbox-triage + merge + ip-sweep commits),
  never pushed — vault is a read replica; next pull merges cleanly, or the
  commits can be cherry-picked upstream.
- `mddb-memory-standard.service` still exits 1 — **by design** (`return 0
  if verdict == PASS else 1`); it's flagging a real memory-standard breach,
  failing since before this work. Worth a follow-up look at the violations.
- obsidian `server.py` hostname change takes effect on next service restart.
- Snapshot refs on idc03: `stash@{0}`, branch `wip/vault-mods-20261007`,
  `~/vault-untracked-backup-20261007.tgz` — safe to drop once soaked.

## How to verify

```sh
ssh idc03 'cd ~/CascadeProjects/chaba-vault && git status -sb && \
  git rev-list --count HEAD..origin/master && \
  grep -rl 100.74.146.0 scripts/ apps/ | wc -l && \
  systemctl --user start ada-memory-sync.service'
```

Job record: `docs/ssot/jobs/infrastructure/2026-10-07-idc03-vault-checkout-convergence.yml`
