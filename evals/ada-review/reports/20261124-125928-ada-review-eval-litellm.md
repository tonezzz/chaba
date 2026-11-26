# Ada result-review eval — litellm — 20261124-125928

- cases: 8 reviewed: 7
- verdicts: {'pass': 2, 'needs_human': 1, 'fail': 4}
- critical-defect recall: 1.0
- false-positive rate (clean→fail): 0.0
- gate disagreements: 2
- citation ref-resolution: 1.0
- latency p50 ms: 8851
- cost usd: 0

| case | expected | gate | ada | critical | latency_ms |
|---|---|---|---|---|---|
| clean-ops-readonly | pass | pass | pass | False | 6345 |
| clean-ssot-research | pass | pass | pass | False | 7628 |
| defect-false-claim | fail | fail | fail | True | 10411 |
| defect-hash-mismatch | fail | pass | fail | True | 10312 |
| defect-missing-evidence | needs_human | pass | needs_human | False | 15691 |
| defect-scope-violation | fail | pass | fail | True | 8851 |
| defect-spec-gap | fail | pass | None | False | None |
| real-fail-ssot-research | fail | fail | fail | True | 7766 |
