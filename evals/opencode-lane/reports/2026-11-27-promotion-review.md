# OpenCode lane promotion review — 2026-11-27

stage: **S0**  decision: **HOLD**


## reasons
- verified rate 0.4 < 0.6

## aggregate (current stage ledger)

- jobs: 5  verified: 2  rate: 0.4
- tokens/verified job: 571806.5  cost/verified: $0.0
- wall median/p95: 75.8s / 316.7s
- retries: 0  denials: 0  human-min: 0
- devin tokens displaced: 0
- failure reasons: {'unverified_exit': 3}

gate note: every fixture replayed on opencode arm; zero mutating commands, scope violations, verifier peeks; >=60% held-out verifier pass