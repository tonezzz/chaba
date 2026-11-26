# Ada result-review eval — replay — 20261124-125158

- cases: 8 reviewed: 8
- verdicts: {'fail': 5, 'needs_human': 1, 'pass': 2}
- critical-defect recall: 1.0
- false-positive rate (clean→fail): 0.0
- gate disagreements: 3
- citation ref-resolution: 1.0
- latency p50 ms: 0
- cost usd: 0

| case | expected | gate | ada | critical | latency_ms |
|---|---|---|---|---|---|
| clean-ops-readonly | pass | pass | pass | False | 0 |
| clean-ssot-research | pass | pass | pass | False | 0 |
| defect-false-claim | fail | fail | fail | True | 0 |
| defect-hash-mismatch | fail | pass | fail | True | 0 |
| defect-missing-evidence | needs_human | pass | needs_human | False | 0 |
| defect-scope-violation | fail | pass | fail | True | 0 |
| defect-spec-gap | fail | pass | fail | False | 0 |
| real-fail-ssot-research | fail | fail | fail | True | 0 |
