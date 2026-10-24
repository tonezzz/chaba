# Offline draft judge — saved Colab T4 filings

This grades preserved HTML filings only; neither model lane was rerun.
The judge was Gemini 3.5 Flash Lite through the free key. The same model
class is used by the current production lane, so these scores are useful
for rubric review but are not an independent promotion signal.

| condition | drafts | mean / 5 | direct answer | accuracy | structure | hygiene | length |
|---|---:|---:|---:|---:|---:|---:|---:|
| gpt-oss:20b T4, no topic context | 8 | 4.700 | 4.875 | 4.875 | 5.000 | 5.000 | 3.750 |
| gpt-oss:20b T4, `--agent-topics` | 7 | 4.714 | 5.000 | 5.000 | 5.000 | 5.000 | 3.571 |

Draft quality is effectively tied; the store-aware prompt shows no measured
quality lift or regression in this one-rep comparison. Length is the weakest
axis in both groups. The rubric did not receive a gold answer or full
transcript, so its accuracy axis is not a substitute for factual adjudication.

Raw grades: `reports/bench-edu-draft-judge-2026-10-24.json`.
