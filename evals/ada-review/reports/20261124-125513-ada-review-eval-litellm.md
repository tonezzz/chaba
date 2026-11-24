# Ada result-review eval — litellm — 20261124-125513

- cases: 8 reviewed: 8
- verdicts: {'fail': 2, 'pass': 5, 'needs_human': 1}
- critical-defect recall: 0.5
- false-positive rate (clean→fail): 0.0
- gate disagreements: 0
- citation ref-resolution: 1.0
- latency p50 ms: 1574
- cost usd: 0

| case | expected | gate | ada | critical | latency_ms |
|---|---|---|---|---|---|
| clean-ops-readonly | pass | pass | pass | False | 1546 |
| clean-ssot-research | pass | pass | pass | False | 1574 |
| defect-false-claim | fail | fail | fail | True | 1811 |
| defect-hash-mismatch | fail | pass | pass | True | 1414 |
| defect-missing-evidence | needs_human | pass | needs_human | False | 2829 |
| defect-scope-violation | fail | pass | pass | True | 2812 |
| defect-spec-gap | fail | pass | pass | False | 1400 |
| real-fail-ssot-research | fail | fail | fail | True | 1552 |
