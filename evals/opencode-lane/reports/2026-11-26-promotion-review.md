# OpenCode lane promotion review — 2026-11-26

stage: **S1**  decision: **ROLLBACK**

rollback to: **S0**

## reasons
- 4 safety-critical failure(s): scope_violation

## aggregate (current stage ledger)

- jobs: 39  verified: 3  rate: 0.077
- tokens/verified job: 95859.0  cost/verified: $0.0645
- wall median/p95: 5.7s / 421.6s
- retries: 3  denials: 0  human-min: 4.930436314392743
- devin tokens displaced: 0
- failure reasons: {'unverified_exit': 2, 'missing_artifact': 6, 'profile_denied_model': 3, 'quota_exceeded': 7, 'stale_heartbeat': 2, 'timeout': 7, 'scope_violation': 4, 'profile_schema_mismatch': 5}

gate note: canary artifact + verifier pass + human watched