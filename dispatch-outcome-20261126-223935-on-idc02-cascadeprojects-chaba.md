# Dispatch outcome — idc02 exec checkout staged-residue converge

Card: `idc02-exec-checkout-117-staged-files-of-70de51` (OPS-1457)
Host operated on: **idc02** `~/CascadeProjects/chaba` (via ssh from con01 dispatch worktree)
Date: 2026-11-26 ~22:40–23:05 +07

## What was found

The card's "~117 staged files" was stale — actual state at inventory time
(22:49) was **709 staged paths** (646 `M `, 62 `D `, 4 `MM`), **1 unmerged**
path (`ansible/playbooks/log-shipper.yml`, UU), and ~37 untracked entries.
Root cause confirmed as autostash-pop residue: the 22:00:09 `chaba-repo-sync`
run stashed the accumulated dirty state (stash@{0}, base c0efc6fe4b),
fast-forwarded to 2d1e83ffa2 at 22:00:10, and the pop left merge results in
the index + worktree with non-generated conflicts resolved to HEAD and local
sides preserved as `.local-conflict-*` sidecars. Earlier runs (10:00, 18:00,
20:00) had left stash@{1..3} the same way. A second manual/safe-pull pass at
~22:46 resolved the remaining UU and added
`log-shipper.yml.local-conflict-20261126-224603`.

## Verification that staged content was residue, not work

- Index blobs classified against HEAD + stash@{0..3}, stash@{0}^2 (index
  commit): only **6 index-unique paths**, all accounted for below.
- Worktree blobs classified the same way: **17 worktree-unique paths**.
- The bulk (~700 files) matched stash trees or were merge products of
  pre-pull content — pure residue.

### Genuine uncommitted local work identified (preserved, NOT discarded)

| Path | Evidence |
|---|---|
| `scripts/ops/rotate-or-key.sh` | worktree sha256 = `e2dae6ff…ced4fb` = the deployment pin declared in job spec `docs/ssot/jobs/security/2026-11-26-rotate-or-key-store3-path-fix.yml` (store-3 repoint mddb-gemini.env→litellm.env) |
| `docs/ssot/infrastructure/ssot.secrets.yml` | slot-status corrections from secrets-compliance pilot (mddb-follower.env, litellm.env, retired-slot markers) |
| `docs/ssot/infrastructure/ssot.llm-gateway.yml` | corrected litellm.env rotation note |
| `ansible/README.md` | +42-line "Secrets slot compliance" section documenting the new playbooks |
| `docs/ssot/infrastructure/ssot.jobs.yml` | local edit(s): earlier removed `jevnest-kk-llm-metrics` job; post-pull re-dirtied with `expected_alert_exit:` additions for watch jobs |
| `scripts/ops/job-health-sweep.py` | in-flight `expected_alert_exit`/`ALERT_EXIT_MARKERS` feature (re-dirtied after reset — active idc02 runner job `job-health-sweep-consecutive-failure-alerts`, action.status=running runner:idc02) |
| 7 kanban card ymls | worktree copies were strictly OLDER than HEAD (missing newer comms, `updated:` regressed) — stale residue, not work; index copies were card-union merge products |
| `systemd/generated/con01/cline-*` (4) | absent from worktree; generated units, regenerable |

Untracked files (new playbooks `secrets-compliance.yml`,
`remediate-secret-file-modes.yml`, `remediate-secret-dir-modes.yml`,
`deploy-rotate-or-key.yml`; job report specs; `.local-conflict-*` sidecars;
experiments) were never touched by the converge.

## What was done

1. Inventoried: `git status --short`, `git diff --cached --stat`
   (709 files, +1604/−10866 — index held pre-pull-ish tree),
   `git ls-files -u`, `git stash list`, reflog, sidecar scan.
2. Verified residue vs work via blob-hash classification (index + worktree
   vs HEAD and all autostash/stash-index trees).
3. Preservation bundle on idc02:
   `~/.local/share/chaba-stash-archive/idc02-rescue-20261126/`
   - `worktree-vs-HEAD.patch` (25k lines, vs pre-pull HEAD 2d1e83ffa2)
   - `index-vs-HEAD.patch`
   - `post-pull-local-edits.patch` + `ssot.secrets.post-reset.yml` (post-reset writes)
   - `untracked-files.tar.gz`, `status-porcelain.txt`, `status-final.txt`,
     `staged-paths.txt`, `README.txt`, `log-shipper.worktree.yml`
   - stash@{0..3} autostash entries also remain in the repo as recovery layer.
4. `git reset --hard HEAD` → tracked tree clean; then
   `bash scripts/git-safe-pull.sh ~/CascadeProjects/chaba` → **exit 0**
   (pull phase 22s, runner-tools refreshed). Ran a second time after the
   23:00 timer tick → **exit 0**, HEAD==origin/master (0/0).
5. The **23:00:00 chaba-repo-sync.service run Finished successfully** —
   the first clean exit after the failure streak; its autostash popped the
   single `ssot.secrets.yml` edit cleanly.

## Final state on idc02 `~/CascadeProjects/chaba`

- HEAD = origin/master (converged; upstream churn means it drifts a few
  commits between hourly syncs — normal).
- `git status`: ~37 untracked (sidecars + new job/playbook files — expected)
  + 3 unstaged modifications that are **live in-flight job work**,
  re-dirtied after the reset by the still-running idc02 jobs:
  `ssot.jobs.yml` (expected_alert_exit), `ssot.secrets.yml` (slot statuses),
  `scripts/ops/job-health-sweep.py` (alert-exit markers). These ride the
  normal autostash cycle; pops are clean → exit 0.
- No conflict markers in tracked files.

## Runner-tooling pin check (card step 5)

Card pin `4259ca6f…` is **stale** — it was the fleet pin earlier today;
`scripts/board/runner-agent.py` changed upstream today (commits 9948bb0fb6,
264f961688) and `scripts/devin/runner-tooling.manifest.json` re-pinned.
Verified consistent at the CURRENT pin on idc02:
installed `~/.local/bin/runner-agent` = repo `scripts/board/runner-agent.py`
= manifest = sha256 `4ed3afdb49f55cb0…`; devin-dispatch `705bfff9…` and
dispatch_repos.py `75292315…` also match manifest. `devin-dispatch.sh` in the
checkout is clean (the earlier "dirty — skipped" warn is gone post-reset).

## Follow-up risk (worth a card)

Exec-checkout jobs keep leaving canonical-source edits uncommitted
(rotate-or-key repoint, secrets slot corrections, job-health-sweep feature,
ssot.jobs.yml edits). Each sync now autostashes+pops them cleanly, but they
remain un-landed local work — the next upstream touch of the same files can
re-create pop conflicts. Recommend a dispatch to apply
`idc02-rescue-20261126/*.patch` + current dirty diffs in a worktree and land
them via the normal push path, then decide whether these job classes should
commit via worktree instead of editing the exec checkout.

## How to verify

```bash
ssh idc02 'cd ~/CascadeProjects/chaba && git status --short | head;
  journalctl --user -u chaba-repo-sync.service -n 10 --no-pager'
# expect: Finished chaba-repo-sync.service, no FAILURE; status shows only
# ?? untracked + a few unstaged job edits
ls ~/.local/share/chaba-stash-archive/idc02-rescue-20261126/   # on idc02
```

lessons:
- Card said ~117 staged files; reality was 709 — always re-inventory, card estimates go stale within hours on this repo.
- `git stash list --format` + blob-hash classify (worktree/index vs HEAD vs every stash tree) is the fast way to prove staged content is autostash residue vs genuine work before a hard reset.
- idc02 exec checkout is a LIVE write target: jobs re-dirty it minutes after a reset (job-health-sweep, secrets-compliance streams) — check mtimes/processes before and after converging, and preserve post-reset edits too.
- The "pin 4259ca6f" in card specs refers to runner-tooling.manifest.json sha256 pins, which re-pin whenever runner-agent.py changes upstream — verify against the manifest, not the card text.
- `git show :N:path` fails once a 22:46-style second safe-pull resolves the UU — save stage blobs AND the worktree copy early; sidecars + patches cover it anyway.
