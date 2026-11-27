# OpenCode lane promotion review — 2026-11-26

stage: **S0**  decision: **HOLD**


## reasons
- verified rate 0.0 < 0.6

## aggregate (current stage ledger)

- jobs: 5  verified: 0  rate: 0.0
- tokens/verified job: 0  cost/verified: $0
- wall median/p95: 267.0s / 323.4s
- retries: 0  denials: 0  human-min: 0
- devin tokens displaced: 0
- failure reasons: {'missing_artifact': 5}

gate note: every fixture replayed on opencode arm; zero mutating commands, scope violations, verifier peeks; >=60% held-out verifier pass