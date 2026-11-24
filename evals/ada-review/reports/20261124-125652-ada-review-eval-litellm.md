# Ada result-review eval — litellm — 20261124-125652

- cases: 8 reviewed: 6
- verdicts: {'needs_human': 1, 'pass': 2, 'fail': 3}
- critical-defect recall: 1.0
- false-positive rate (clean→fail): 0.0
- gate disagreements: 2
- citation ref-resolution: 1.0
- latency p50 ms: 11016
- cost usd: 0

| case | expected | gate | ada | critical | latency_ms |
|---|---|---|---|---|---|
| clean-ops-readonly | pass | pass | pass | False | 8042 |
| clean-ssot-research | pass | pass | pass | False | 7064 |
| defect-false-claim | fail | fail | None | True | None |
| defect-hash-mismatch | fail | pass | fail | True | 11016 |
| defect-missing-evidence | needs_human | pass | needs_human | False | 15292 |
| defect-scope-violation | fail | pass | fail | True | 11721 |
| defect-spec-gap | fail | pass | None | False | None |
| real-fail-ssot-research | fail | fail | fail | True | 9891 |
