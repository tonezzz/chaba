# kk-mac task-class eval — lane-verifier run

entity: `kkmac` model: `qwen3:8b` cases: 51 latency mean 34.0s total 1732.0s

Scored by the production verifier (kk_mac_executor.verify): a case passes only when the lane would return verdict=pass on this exact response.

| task_class | n | pass_rate | json_parse | verdict |
|---|---|---|---|---|
| operator_brief (HELD — not admitted) | 16 | 0.9375 | 1.0 | READY |
| safe_route (HELD — not admitted) | 15 | 0.5333 | 1.0 | not ready |
| structured_extract | 15 | 0.9333 | 1.0 | READY |
| summary | 5 | 0.6 | - | not ready |
| **overall** | 51 | **0.7843** | - | - |

transport_failures: 0 (bar: 0)

NOTE: provisional readiness bar — pass_rate >= 0.8 per class, json_parse >= 0.9. ~15 cases/class is a smoke screen, not the T3 gate.

## check-failure histogram (failed check -> count)
```json
{
  "fact:claim": 2,
  "fact:correct": 2,
  "fact:task_class": 1,
  "fact:429": 1,
  "fact:defer": 1,
  "fact:clarify": 1,
  "fact:close": 1,
  "fact:ollama": 1,
  "fact:61": 1,
  "fact:launchd": 1
}
```

## per-case

| case | class | verdict | failed checks | s |
|---|---|---|---|---|
| se-host-digest | structured_extract | pass | - | 35.9 |
| se-systemd-unit | structured_extract | pass | - | 22.6 |
| se-kanban-card | structured_extract | pass | - | 13.2 |
| se-heartbeat | structured_extract | pass | - | 16.1 |
| se-log-errors | structured_extract | pass | - | 24.0 |
| se-invoice | structured_extract | pass | - | 25.3 |
| se-ha-entities | structured_extract | pass | - | 19.9 |
| se-bench-result | structured_extract | pass | - | 15.3 |
| se-pr-status | structured_extract | pass | - | 13.6 |
| se-git-log | structured_extract | fail | fact:task_class | 11.7 |
| se-probe-results | structured_extract | pass | - | 19.6 |
| se-host-inventory | structured_extract | pass | - | 30.2 |
| se-missing-fields | structured_extract | pass | - | 13.4 |
| se-audit-severity | structured_extract | pass | - | 24.8 |
| se-dispatch-outcome | structured_extract | pass | - | 30.5 |
| ob-infra-digest | operator_brief | pass | - | 58.8 |
| ob-failed-units | operator_brief | pass | - | 27.6 |
| ob-spend | operator_brief | pass | - | 27.3 |
| ob-queue | operator_brief | pass | - | 42.9 |
| ob-disk-pressure | operator_brief | pass | - | 30.3 |
| ob-overnight-sessions | operator_brief | pass | - | 161.5 |
| ob-board-hygiene | operator_brief | pass | - | 56.3 |
| ob-tunnel-health | operator_brief | pass | - | 50.8 |
| ob-cert-renewal | operator_brief | pass | - | 114.0 |
| ob-backup | operator_brief | pass | - | 57.7 |
| ob-event-flood | operator_brief | pass | - | 48.5 |
| ob-memory-pressure | operator_brief | pass | - | 39.5 |
| ob-stale-heartbeat | operator_brief | pass | - | 71.2 |
| ob-ratelimit | operator_brief | fail | fact:429 | 32.7 |
| ob-all-clear | operator_brief | pass | - | 32.8 |
| ob-mixed-signal | operator_brief | pass | - | 36.0 |
| sr-armed-spec | safe_route | fail | fact:claim | 26.8 |
| sr-decide-card | safe_route | fail | fact:defer | 17.6 |
| sr-spend-ask | safe_route | pass | - | 21.3 |
| sr-destructive | safe_route | pass | - | 10.4 |
| sr-lane-down | safe_route | pass | - | 21.7 |
| sr-ambiguous-spec | safe_route | fail | fact:clarify | 15.4 |
| sr-verified-done | safe_route | fail | fact:close | 21.1 |
| sr-stale-claim | safe_route | fail | fact:correct | 9.9 |
| sr-cap-reached | safe_route | pass | - | 23.0 |
| sr-high-pri-prod | safe_route | pass | - | 23.3 |
| sr-routine-healthy | safe_route | pass | - | 7.9 |
| sr-duplicate | safe_route | pass | - | 16.8 |
| sr-evidence-contradicts | safe_route | fail | fact:correct | 23.7 |
| sr-credential-ask | safe_route | pass | - | 33.4 |
| sr-bounded-summary | safe_route | fail | fact:claim | 25.7 |
| sm-control-digest | summary | pass | - | 37.5 |
| sm-control-heartbeat | summary | fail | fact:ollama fact:61 | 28.7 |
| sm-control-log | summary | pass | - | 31.7 |
| sm-control-card | summary | fail | fact:launchd | 27.5 |
| sm-control-outcome | summary | pass | - | 104.6 |
