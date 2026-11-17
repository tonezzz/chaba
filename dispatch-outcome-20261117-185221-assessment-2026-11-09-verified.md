# Dispatch outcome — devnest-queue-consolidation tracker re-verify (2026-11-17)

## What this session did

The card `devnest-queue-consolidation` is a tracker (marked "do not dispatch"
after its 2026-11-09 decomposition into ops-1244a..f) that got claimed anyway.
Used the session to re-verify every done-condition item against live state on
all 4 runners and to retire the two remaining live vestiges on idc03.

## Changes made (live, reversible)

- **idc03: `kanban-dispatch.timer` disabled --now.** It was still enabled and
  crashing every 2min tick (`AttributeError: 'str' object` on the scalar
  `action:` in the served `nest-mgr-v2-actuation` card — repo card was fixed by
  4eba1f957c but the served copy still returns a scalar). ~720 failed service
  starts/day of noise; zero claim value since it never got past the crash.
- **idc03: `chaba-jobs.timer` disabled --now.** The job-dispatcher vestige was
  still enabled, firing an empty tick every 1min (zero `dispatch: dispatcher`
  jobs exist in ssot.jobs.yml). Pure noise.
- Rollback for both: `systemctl --user enable --now <unit>` on idc03 (unit
  files untouched).
- Trail doc: `docs/ssot/jobs/devnest/2026-11-17-queue-consolidation-verify.yml`
- Board: status comment on `devnest-queue-consolidation`; reroute request
  raised on `ops-1244b-one-claimer-jules` (jules lane EOL — devin lane
  recommended).

## Done-condition verdict (verified live ~19:00 ICT)

| Item | State |
|---|---|
| Queue drains on claimer restart | PASS — runner-agent.timer enabled+active on idc03/idc02/mn01/tony-omen; installed binaries all md5 `e17fb02…` == repo; queue 25→15, 6 claims running |
| Exactly one unit family claims | PASS (after this session) — runner-agent only; kanban-dispatch retired on idc03 |
| ssot.jobs.yml only catalog | PASS — 0 dispatcher jobs in repo; generated views; last live tick vestige retired |
| nest queue watch = 1 unit | PASS — one job, 15m on idc03 |
| No dispatch-typed timer-alerts | PASS at producer (sentinel emits no action block); 24 legacy cards keep type=dispatch but all done — cosmetic |

## Open gaps (not this session's scope)

- `ops-1244b-one-claimer-jules` — the only open sub-card; blocked on reroute
  (jules lane EOL until Dec 31). Board request raised for Tony.
- focus-inbox unprocessed grew 546 → 1665 (974 Nov-dated); the /inbox fold
  of intake never happened — file queue still accumulates.
- Served `nest-mgr-v2-actuation` card still has scalar `action:` — breaks raw
  YAML consumers; needs the 4eba1f957c shape live on the served checkout.
- runner-agent deploy is still manual scp (not in render catalog) —
  ops-1244b scope.

## How to verify

- `ssh idc03 'systemctl --user list-timers | grep -E "runner|kanban|chaba-jobs"'`
  → only `runner-agent.timer`.
- `ssh <runner> 'md5sum ~/.local/bin/runner-agent'` == `md5sum scripts/board/runner-agent.py`.
- Board: queued count + `comms` on `devnest-queue-consolidation`.
