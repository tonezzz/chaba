# dispatch-outcome — raise-kanban-dispatch-parallel (card dispatch-concurrency-bump-idc)

## What the card asked
Check per-host dispatch caps on idc02/idc03 runner-agents; bump to allow
≥2 concurrent card tasks/host where memory allows.

## What was found (live audit, 2026-10-27)
- **idc02**: `RUNNER_CAP=3` in the base unit — already above the 2 target.
  15.6G total / ~8G available, load ~0.4-0.5/core. Timer active.
- **idc03**: base unit `RUNNER_CAP=2` but a `cap.conf` drop-in dated
  **2026-10-09** already raises it to **cap 3 + gate 0.85** — the bump was
  applied weeks ago; `ssot.kanban.yml` `runner_fleet` still recorded
  "cap 2" (doc drift). 15.6G total but only ~5G available (board-api,
  ada, kanban-commit co-resident). Timer active.
- Both hosts therefore already exceed the card's requested parallelism.
- Cap 4 was evaluated and **refused**: the floor(mem_total/3.5) formula
  allows 4, but available memory is the real budget — a 4th ~3.5GB
  session against ~5G available on idc03 leaves ~1.5G for all
  co-resident services. Cap 3 (~10.5G worst case) is the safe ceiling on
  both hosts.

## Changes (committed on session branch, not pushed)
- `docs/ssot/kanban/ssot.kanban.yml` — runner_fleet corrected: idc03
  cap 3 gate 0.85 (was "cap 2"), audit note + refusal rationale added.
- `scripts/board/runner-cap.sh` — `remote()` short-circuits to `bash -c`
  when HOST is the local nodename; self-ssh is unprovisioned on idc02
  (publickey denied) so `runner-cap.sh idc02 show` run on idc02 silently
  printed nothing before.
- `docs/ssot/jobs/kanban/2026-10-27-runner-cap-audit-idc.yml` — audit
  record, ceiling rule (gate on MemAvailable not MemTotal), ops notes.

## Verification
- `bash scripts/board/runner-cap.sh idc02 show` on idc02 now prints the
  effective env (RUNNER_CAP=3) + mem/load — local path works.
- `ssh idc03 'systemctl --user cat runner-agent.service | grep
  Environment'` shows RUNNER_CAP=3 via drop-in + gate 0.85.
- `systemctl --user list-timers runner-agent.timer` active on both hosts.
- YAML validated; runner-agent unit tests (lane, push-guard, gpu) pass.

## Result
No live change needed — parallelism already above target on both hosts;
SSOT drift fixed and the ceiling decision + procedure fix are documented
for the next audit.
