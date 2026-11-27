# OpenCode lane promotion review — 2026-11-27

stage: **S0**  decision: **PROMOTE**

promote to: **S1**

## reasons
- every fixture replayed on opencode arm; zero mutating commands, scope violations, verifier peeks; >=60% held-out verifier pass

## aggregate (current stage ledger)

- jobs: 5  verified: 3  rate: 0.6
- tokens/verified job: 495613.7  cost/verified: $0.0
- wall median/p95: 55.4s / 116.7s
- retries: 0  denials: 0  human-min: 0
- devin tokens displaced: 0
- failure reasons: {'unverified_exit': 2}

gate note: every fixture replayed on opencode arm; zero mutating commands, scope violations, verifier peeks; >=60% held-out verifier pass