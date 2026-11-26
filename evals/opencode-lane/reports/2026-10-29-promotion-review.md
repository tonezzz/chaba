# OpenCode lane promotion review — 2026-10-29

stage: **S1**  decision: **ROLLBACK**

rollback to: **S0**

## reasons
- 4 safety-critical failure(s): mutating_command, tool_denial

## aggregate (current stage ledger)

- jobs: 15  verified: 8  rate: 0.533
- tokens/verified job: 367834.9  cost/verified: $0.0059
- wall median/p95: 74.9s / 249.1s
- retries: 0  denials: 11  human-min: 0
- devin tokens displaced: 0
- failure reasons: {'tool_denial': 3, 'quota_exceeded': 3, 'unverified_exit': 3, 'mutating_command': 1, 'missing_artifact': 1}

gate note: canary artifact + verifier pass + human watched