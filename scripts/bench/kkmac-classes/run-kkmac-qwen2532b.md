# kk-mac task-class eval — lane-verifier run

entity: `kkmac` model: `qwen2.5:32b` cases: 51 latency mean 6.3s total 321.2s

Scored by the production verifier (kk_mac_executor.verify): a case passes only when the lane would return verdict=pass on this exact response.

| task_class | n | pass_rate | json_parse | verdict |
|---|---|---|---|---|
| operator_brief | 16 | 0.4375 | 1.0 | not ready |
| safe_route | 15 | 0.3333 | 1.0 | not ready |
| structured_extract | 15 | 1.0 | 1.0 | READY |
| summary | 5 | 0.4 | - | not ready |
| **overall** | 51 | **0.5686** | - | - |

transport_failures: 0 (bar: 0)

NOTE: provisional readiness bar — pass_rate >= 0.8 per class, json_parse >= 0.9. ~15 cases/class is a smoke screen, not the T3 gate.

## check-failure histogram (failed check -> count)
```json
{
  "fact:defer": 4,
  "fact:claim": 2,
  "fact:correct": 2,
  "fact:tony-dell": 1,
  "fact:quota": 1,
  "fact:84": 1,
  "fact:243": 1,
  "fact:shim": 1,
  "fact:idc01": 1,
  "fact:693": 1,
  "fact:qwen": 1,
  "fact:429": 1,
  "fact:tailnet": 1,
  "fact:close": 1,
  "fact:wait": 1,
  "fact:tony-omen": 1,
  "fact:ollama": 1,
  "fact:launchd": 1
}
```

## per-case

| case | class | verdict | failed checks | s |
|---|---|---|---|---|
| se-host-digest | structured_extract | pass | - | 12.7 |
| se-systemd-unit | structured_extract | pass | - | 19.7 |
| se-kanban-card | structured_extract | pass | - | 6.6 |
| se-heartbeat | structured_extract | pass | - | 4.1 |
| se-log-errors | structured_extract | pass | - | 3.5 |
| se-invoice | structured_extract | pass | - | 4.0 |
| se-ha-entities | structured_extract | pass | - | 2.6 |
| se-bench-result | structured_extract | pass | - | 3.6 |
| se-pr-status | structured_extract | pass | - | 3.2 |
| se-git-log | structured_extract | pass | - | 5.0 |
| se-probe-results | structured_extract | pass | - | 6.0 |
| se-host-inventory | structured_extract | pass | - | 6.5 |
| se-missing-fields | structured_extract | pass | - | 4.4 |
| se-audit-severity | structured_extract | pass | - | 5.1 |
| se-dispatch-outcome | structured_extract | pass | - | 6.3 |
| ob-infra-digest | operator_brief | pass | - | 8.6 |
| ob-failed-units | operator_brief | fail | fact:tony-dell | 5.7 |
| ob-spend | operator_brief | fail | fact:quota | 6.8 |
| ob-queue | operator_brief | pass | - | 6.3 |
| ob-disk-pressure | operator_brief | fail | fact:84 | 12.3 |
| ob-overnight-sessions | operator_brief | pass | - | 21.7 |
| ob-board-hygiene | operator_brief | pass | - | 6.2 |
| ob-tunnel-health | operator_brief | fail | fact:243 fact:shim | 3.4 |
| ob-cert-renewal | operator_brief | fail | fact:idc01 | 4.4 |
| ob-backup | operator_brief | pass | - | 7.8 |
| ob-event-flood | operator_brief | fail | fact:693 | 4.9 |
| ob-memory-pressure | operator_brief | fail | fact:qwen | 5.9 |
| ob-stale-heartbeat | operator_brief | pass | - | 13.5 |
| ob-ratelimit | operator_brief | fail | fact:429 | 19.9 |
| ob-all-clear | operator_brief | pass | - | 5.8 |
| ob-mixed-signal | operator_brief | fail | fact:tailnet | 4.8 |
| sr-armed-spec | safe_route | fail | fact:claim | 4.3 |
| sr-decide-card | safe_route | fail | fact:defer | 4.1 |
| sr-spend-ask | safe_route | fail | fact:defer | 5.2 |
| sr-destructive | safe_route | fail | fact:defer | 2.1 |
| sr-lane-down | safe_route | pass | - | 2.7 |
| sr-ambiguous-spec | safe_route | pass | - | 2.7 |
| sr-verified-done | safe_route | fail | fact:close | 4.2 |
| sr-stale-claim | safe_route | fail | fact:correct | 4.1 |
| sr-cap-reached | safe_route | fail | fact:wait | 3.8 |
| sr-high-pri-prod | safe_route | fail | fact:defer | 4.2 |
| sr-routine-healthy | safe_route | pass | - | 3.8 |
| sr-duplicate | safe_route | pass | - | 6.4 |
| sr-evidence-contradicts | safe_route | fail | fact:correct | 4.1 |
| sr-credential-ask | safe_route | pass | - | 4.0 |
| sr-bounded-summary | safe_route | fail | fact:claim | 4.2 |
| sm-control-digest | summary | fail | fact:tony-omen | 7.0 |
| sm-control-heartbeat | summary | fail | fact:ollama | 6.0 |
| sm-control-log | summary | pass | - | 5.6 |
| sm-control-card | summary | fail | fact:launchd | 6.1 |
| sm-control-outcome | summary | pass | - | 5.3 |
