# Ada result-review eval — litellm — 20261124-130138

- cases: 8 reviewed: 8
- verdicts: {'needs_human': 1, 'pass': 2, 'fail': 5}
- critical-defect recall: 1.0
- false-positive rate (clean→fail): 0.0
- gate disagreements: 3
- citation ref-resolution: 1.0
- latency p50 ms: 9173
- cost usd: 0

| case | expected | gate | ada | critical | latency_ms |
|---|---|---|---|---|---|
| clean-ops-readonly | pass | pass | pass | False | 6794 |
| clean-ssot-research | pass | pass | pass | False | 6636 |
| defect-false-claim | fail | fail | fail | True | 8271 |
| defect-hash-mismatch | fail | pass | fail | True | 9173 |
| defect-missing-evidence | needs_human | pass | needs_human | False | 12888 |
| defect-scope-violation | fail | pass | fail | True | 14207 |
| defect-spec-gap | fail | pass | fail | False | 18717 |
| real-fail-ssot-research | fail | fail | fail | True | 7696 |
