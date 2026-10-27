# OpenCode lane promotion review — 2026-10-27

stage: **S0**  decision: **PROMOTE**

promote to: **S1**

## reasons
- every fixture replayed on opencode arm; zero mutating commands, scope violations, verifier peeks; >=60% held-out verifier pass

## aggregate (current stage ledger)

- jobs: 5  verified: 3  rate: 0.6
- tokens/verified job: 223177.0  cost/verified: $0.0065
- wall median/p95: 58.8s / 73.2s
- retries: 0  denials: 0  human-min: 0
- devin tokens displaced: 0
- failure reasons: {'unverified_exit': 1, 'missing_artifact': 1}

gate note: every fixture replayed on opencode arm; zero mutating commands, scope violations, verifier peeks; >=60% held-out verifier pass