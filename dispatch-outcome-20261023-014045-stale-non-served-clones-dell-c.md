# Dispatch outcome — stale non-served clones (dell ~/CascadeProjects/chaba)

Card: stale-non-served-clones-dell-cascadeproj-efbd23 (BEN-0703), runner mn01, 2026-10-23.

## Verified end-state on dell

- **Original complaint is already fixed**: `~/CascadeProjects/chaba` (exec checkout, role=exec) is kept current by `chaba-repo-sync.timer` at 15-min cadence (installed 2026-10-16, OPS-0479). Verified live: timer ticking, last run exit 0. Mid-gap behindness (observed 99) is inter-tick drift from board commit bursts — it converges every tick.
- **Tony's "proceed" executed**: both stale worktrees reaped by the 08:19/08:34 sweep — `chaba-kanban-sync` and `chaba-tony-dell-experiment` removed, diffs archived to `~/backups/worktree-reap-20261023/*.patch`, `kanban-sync.{service,timer}.parked` deleted.

## Topology correction (the real trap fix)

- **The writer is on idc03, not dell** (OPS-0725 cutover, 2026-10-17). dell's `chaba-tony-dell` is a frozen pull-only mirror synced hourly by `chaba-served-mirror-sync.timer`; its `role=readonly` marker is CORRECT — do not "fix" it. kanban-commit/board-api run from idc03's `~/CascadeProjects/chaba-tony-dell` (role=served).
- AGENTS.md single-writer/write-path/exec-sync lines were stale (still described dell as writer) — corrected in this branch.

## Changes landed on this branch (69b66241 + 9d7483c1)

- `AGENTS.md`: writer topology corrected (dell=mirror readonly, idc03=served), role map recorded, `readonly` added to role list.
- `docs/ssot/jobs/infrastructure/2026-10-22-dell-non-served-chaba-clones.yml`: 2026-10-23 verified-state addendum + revised followups.
- Live role stamps (safe, informational until hooks arm): dell mirror worktrees iphone-dev/nest-lane/tony-ha=`branch`, detached master=`job`; idc03 chaba=`exec`, chaba-tony-dell=`served`, chaba-kanban-sync/chaba-vault=`job`.

## New traps found → board request raised (pending Tony)

- dell mirror has 4 stale linked worktrees: iphone-dev (0 unmerged, 7wk), master-detached (0 unmerged, 4wk), nest-lane (1 unmerged, 2wk), tony-ha (45 unmerged, 6wk, 4 dirty). `git worktree remove` preserves branch refs — non-destructive after archiving tony-ha's dirty files.
- idc03 has two dead backup trees on the writer host: `chaba-kanban-sync.bak-20261019` (209M) + `chaba-tony-dell.livebak-20261018` (**7.2G**) — hygiene violations and prime confusion traps.
- Request `reap-the-remaining-stale-clone-traps-1-d-36c042` raised with recommendation: proceed (archive-first).

## Not in scope / noted

- `chaba-raceman` on dell is NOT a git clone — separate app backing live `raceman-php.service`; confusable name only.
- ~50 `.parked` units on dell (incl. drained writer units) — belongs to tony-dell-full-migration card.
- Remaining un-stamped exec checkouts: idc02, con01, tony_omen, macbook — stamp on next touch.
- mn01 exec checkout's 14 uncommitted focus-inbox files — still a pending decision (single-writer).

## How to verify

- `ssh tony-dell 'systemctl --user list-timers chaba-repo-sync.timer chaba-served-mirror-sync.timer; git -C ~/CascadeProjects/chaba status -sb; cat ~/CascadeProjects/chaba/.git/chaba-role'`
- `ssh idc03 'for d in chaba chaba-tony-dell chaba-kanban-sync chaba-vault; do echo -n "$d "; cat ~/CascadeProjects/$d/.git/chaba-role; done'`
- Card board: request `reap-the-remaining-stale-clone-traps-1-d-36c042` awaiting answer.
