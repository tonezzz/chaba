# kk-mac task-class eval — lane-verifier run

entity: `kkmac` model: `llama3.2:3b` cases: 51 latency mean 1.1s total 53.8s

Scored by the production verifier (kk_mac_executor.verify): a case passes only when the lane would return verdict=pass on this exact response.

| task_class | n | pass_rate | json_parse | verdict |
|---|---|---|---|---|
| operator_brief | 16 | 0.3125 | 1.0 | not ready |
| safe_route | 15 | 0.6 | 1.0 | not ready |
| structured_extract | 15 | 1.0 | 1.0 | READY |
| summary | 5 | 0.6 | - | not ready |
| **overall** | 51 | **0.6275** | - | - |

transport_failures: 0 (bar: 0)

NOTE: provisional readiness bar — pass_rate >= 0.8 per class, json_parse >= 0.9. ~15 cases/class is a smoke screen, not the T3 gate.

## check-failure histogram (failed check -> count)
```json
{
  "fact:tony-dell": 2,
  "fact:defer": 2,
  "fact:idc02": 1,
  "fact:84": 1,
  "fact:6": 1,
  "fact:243": 1,
  "fact:11": 1,
  "fact:693": 1,
  "fact:qwen": 1,
  "fact:22": 1,
  "fact:fallback": 1,
  "fact:429": 1,
  "fact:clarify": 1,
  "fact:close": 1,
  "fact:correct": 1,
  "fact:observe": 1,
  "fact:tony-omen": 1,
  "fact:ollama": 1
}
```

## per-case

| case | class | verdict | failed checks | s |
|---|---|---|---|---|
| se-host-digest | structured_extract | pass | - | 2.4 |
| se-systemd-unit | structured_extract | pass | - | 0.6 |
| se-kanban-card | structured_extract | pass | - | 0.6 |
| se-heartbeat | structured_extract | pass | - | 0.7 |
| se-log-errors | structured_extract | pass | - | 0.6 |
| se-invoice | structured_extract | pass | - | 1.9 |
| se-ha-entities | structured_extract | pass | - | 1.2 |
| se-bench-result | structured_extract | pass | - | 1.1 |
| se-pr-status | structured_extract | pass | - | 0.5 |
| se-git-log | structured_extract | pass | - | 0.6 |
| se-probe-results | structured_extract | pass | - | 0.6 |
| se-host-inventory | structured_extract | pass | - | 0.7 |
| se-missing-fields | structured_extract | pass | - | 0.6 |
| se-audit-severity | structured_extract | pass | - | 0.5 |
| se-dispatch-outcome | structured_extract | pass | - | 0.7 |
| ob-infra-digest | operator_brief | fail | fact:tony-dell | 1.2 |
| ob-failed-units | operator_brief | fail | fact:tony-dell | 0.6 |
| ob-spend | operator_brief | pass | - | 1.1 |
| ob-queue | operator_brief | fail | fact:idc02 | 0.7 |
| ob-disk-pressure | operator_brief | fail | fact:84 | 1.6 |
| ob-overnight-sessions | operator_brief | fail | fact:6 | 0.7 |
| ob-board-hygiene | operator_brief | pass | - | 0.6 |
| ob-tunnel-health | operator_brief | fail | fact:243 | 0.6 |
| ob-cert-renewal | operator_brief | fail | fact:11 | 0.6 |
| ob-backup | operator_brief | pass | - | 0.9 |
| ob-event-flood | operator_brief | fail | fact:693 | 0.7 |
| ob-memory-pressure | operator_brief | fail | fact:qwen | 0.7 |
| ob-stale-heartbeat | operator_brief | fail | fact:22 fact:fallback | 0.6 |
| ob-ratelimit | operator_brief | fail | fact:429 | 0.6 |
| ob-all-clear | operator_brief | pass | - | 0.6 |
| ob-mixed-signal | operator_brief | pass | - | 1.6 |
| sr-armed-spec | safe_route | pass | - | 1.2 |
| sr-decide-card | safe_route | fail | fact:defer | 1.3 |
| sr-spend-ask | safe_route | pass | - | 1.0 |
| sr-destructive | safe_route | pass | - | 1.4 |
| sr-lane-down | safe_route | pass | - | 1.5 |
| sr-ambiguous-spec | safe_route | fail | fact:clarify | 1.7 |
| sr-verified-done | safe_route | fail | fact:close | 1.4 |
| sr-stale-claim | safe_route | fail | fact:correct | 1.1 |
| sr-cap-reached | safe_route | pass | - | 1.4 |
| sr-high-pri-prod | safe_route | fail | fact:defer | 1.3 |
| sr-routine-healthy | safe_route | fail | fact:observe | 1.6 |
| sr-duplicate | safe_route | pass | - | 1.1 |
| sr-evidence-contradicts | safe_route | pass | - | 1.5 |
| sr-credential-ask | safe_route | pass | - | 1.4 |
| sr-bounded-summary | safe_route | pass | - | 1.9 |
| sm-control-digest | summary | fail | fact:tony-omen | 1.2 |
| sm-control-heartbeat | summary | fail | fact:ollama | 1.1 |
| sm-control-log | summary | pass | - | 1.6 |
| sm-control-card | summary | pass | - | 1.2 |
| sm-control-outcome | summary | pass | - | 1.2 |
