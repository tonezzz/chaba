# Dispatch outcome — devnest-queue-consolidation tracker verify (attempt 2, 2026-11-23)

## What this session did

`devnest-queue-consolidation` is a tracker (decomposed 2026-11-09 into
ops-1244a..f, marked do-not-dispatch) that Tony requeued for rework after the
2026-11-17 dispatch's merge was held on a test-gate suite timeout and today's
attempt 1 died on a provider rate-limit. This session re-verified every
done-condition item against live state and re-landed the trail doc the held
branch never got to master.

## Prior failures — diagnosis, not repeated

- **2026-11-17** (tony-omen, exit=0): work was sound; merge held on
  `suite timeout (240s)` — the chaba smoke-set gate (added 11-15, ~70s on
  omen) couldn't finish on an overloaded idc03. Environmental, nothing in
  the diff.
- **2026-11-23 15:12** (attempt 1): exit=1 after 8.5min — provider
  rate-limit signature per runner comms. Infra flake.
- No code fix possible for either from a worktree; kept this run small and
  efficient.

## Verified live ~16:00 ICT (tony-omen local + ssh idc03/idc02/mn01 + board-api)

| Done-condition item | Verdict |
|---|---|
| Queue drains on claimer restart | PASS — runner-agent.timer enabled+firing on all 4 runners; installed md5 `e9cbd25…` == repo on all 4; `/queue` live, 13 queued, verdicts flowing |
| Exactly one unit family claims | PASS — `kanban-dispatch.timer` disabled+inactive on idc03 (11-17 retire stuck); runner-agent only |
| ssot.jobs.yml only catalog | PASS — 0 `dispatch: dispatcher` jobs; `chaba-jobs.timer` disabled+inactive; generated per-host views exist |
| nest queue watch = 1 unit | PASS — single `nest-queue-watch.timer` on idc03, 15m |
| No dispatch-typed timer-alerts | PASS — 0 live (was 12/25 on 11-09) |
| ONE JANITOR (bonus check) | PASS — `board-janitor.timer` live on idc03 (11-12 "never installed" gap closed) |
| ARM THE ROUTER | PASS — jev-lane.conf `[Service]`+`JEV_LANE=1` verified on omen/idc02/mn01; queue-time classify live in /queue |

## Key finding — ops-1244b closed without the work landing

`ops-1244b-one-claimer-jules` was archived today as done, but Ada closed it
on 2026-11-20 **because the jules lane was purged** — the one-claimer
refactor (long-running `nest-runner.service` / `runner-agent --loop` +
rendered unit) was never implemented. Verified: no `--loop` in
runner-agent.py, no nest-runner unit in ssot.jobs.yml, deploy is still
manual scp. The 2026-11-08 stall class is mitigated only by timers being
re-enabled, not self-healing. The scope is currently **uncarded** — board
request raised on this card asking whether to re-card on a live lane.

## Other open gaps (unchanged, recorded in trail doc)

- focus-inbox: 2174 unprocessed top-level files (546→1665→2174); `/inbox`
  fold never landed — intake still accumulates outside the card queue.
- Merge test gate still can hold doc-only merges when idc03 is loaded
  (open card `merge-sweep-test-gate-fail-open` queued).
- Served `nest-mgr-v2-actuation` scalar action: FIXED since 11-17 — dict
  now, 0 scalar-action cards board-wide.

## Deliverables

- `docs/ssot/jobs/devnest/2026-11-23-queue-consolidation-verify.yml` —
  full verdict trail, supersedes the unmerged 11-17 doc.
- Card comms: start + final verify summary; request raised re ops-1244b scope.
- No code changes; no live changes (11-17's idc03 disables verified still
  holding — nothing left to flip).

## How to verify

- `ssh <host> 'systemctl --user list-timers | grep runner-agent'` — all 4 runners.
- `ssh idc03 'systemctl --user is-enabled kanban-dispatch.timer chaba-jobs.timer'` → `disabled disabled`.
- `curl -s https://idc03.taila0626a.ts.net:10000/queue` — live queue/verdicts.
- `grep -c 'dispatch: dispatcher' docs/ssot/infrastructure/ssot.jobs.yml` → 0.
- Board: `devnest-queue-consolidation` comms + the open request.

lessons:
- Archived != done: ops-1244b was auto-archived after Ada closed it on the jules lane purge — always check WHY a sub-card closed before claiming the scope landed.
- jev-lane.conf lives at `~/.config/systemd/user/runner-agent.service.d/jev-lane.conf`, not `~/.config/systemd/user/` — wrong-path check gives a false MISSING.
- chaba merge test gate (240s smoke set) times out on loaded idc03 even for doc-only diffs; held merges are environmental, keep the branch small and retry.
- `/cards` needs `-m 40`+ and a file target; it doesn't stream — quick card lookups via `/queue` or saved json are faster.
