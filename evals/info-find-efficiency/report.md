# info-find efficiency — tool-level A/B

Offline, deterministic, read-only. `tokens_est` = bytes/4.

| Task | Kind | A tokens | B tokens | A correct | B correct |
| --- | --- | ---: | ---: | :---: | :---: |
| narrow-1 | narrow | 1698 | 112 | False | True |
| narrow-2 | narrow | 1707 | 115 | False | True |
| narrow-3 | narrow | 1706 | 54 | False | True |
| narrow-4 | narrow | 1701 | 72 | False | True |
| cross-1 | cross | 1705 | 756 | False | True |
| cross-2 | cross | 1698 | 260 | False | True |
| cross-3 | cross | 1683 | 1750 | False | True |
| cross-4 | cross | 1701 | 895 | False | True |

## Medians

| Kind | Arm | tokens | ms | tool calls | correct |
| --- | --- | ---: | ---: | ---: | ---: |
| narrow | info-find | 1703.5 | 7616.5 | 1.0 | 0.0 |
| narrow | direct | 92.0 | 18.5 | 1.0 | 1.0 |
| cross | info-find | 1699.5 | 5487.0 | 1.0 | 0.0 |
| cross | direct | 825.5 | 304.5 | 2.0 | 1.0 |

## Decision

**keep direct tools for narrow lookups; no evidence for cross-source adoption**

Adopt threshold: cross-source info-find tokens ≤ 70% of direct tokens with equal-or-better correctness.

Caveats: tool-level only (no LLM decision overhead), 8 tasks, offline sources, rough token proxy — directional evidence, not conclusive.
