# Adobe Stock multirun — model comparison

Card: `openchamber-multirun-adobe-stock-prompts` · generated 2026-11-25T07:42:06.524006+00:00

Identical read-only brief (campaign `AS-2026-11-05-REMOTE-WORK-001` frozen snapshot) run through approved OpenCode models under a deny-all-tools isolated config. No run uploaded, generated, licensed, or mutated cards/files.

| arm | model | verifier | relevance | provenance | missing-prev | policy | in tok | out tok | cost $ | wall s |
|---|---|---|---|---|---|---|---|---|---|---|
| gemini-3.5-flash-lite | `litellm/gemini-3.5-flash-lite` | pass (clean) | 5 | 5 | 5 | 5 | 36652 | 4030 | 0.0053 | 32.9 |
| or-free-nemotron-ultra | `litellm/or-free-nemotron-ultra` | pass (clean) | 5 | 5 | 5 | 5 | 8639 | 4333 | 0.0000 | 177.7 |
| or-gemini-3.5-flash | `litellm/or-gemini-3.5-flash` | pass (clean) | 5 | 5 | 5 | 5 | 36626 | 4164 | 0.0000 | 53.8 |

**Recommended model: `litellm/or-free-nemotron-ultra`**

Best verified quality per dollar: $0 (:free route), full 16-asset coverage, exact provenance, correct missing-preview set, and the most faithful mapping of canonical qc_decision verdicts to reuse decisions (reject->reject with the illustration-line caveat, revise->remix, pending->hold, baseline->hold). Its upload pick (comparison-e-gemini-fix3-region, the corner-fixed frontier asset) is the most defensible of the three. Cost is latency (177.7s vs 32.9s flash-lite) — acceptable for non-interactive batch briefs; or-gemini-3.5-flash is the balanced paid alternative (53.8s, small OR spend).

### Qualitative read (verifier scores tied at 5/5/5/5)

- `or-free-nemotron-ultra`: textbook verdict mapping — the only arm that held the baseline as `hold` (its QC is keep-for-comparison, not a submission) and `reject`ed the photorealism-failed `comparison-c-omen-sdxl` while preserving the illustration second-product-line note. Upload pick `comparison-e-gemini-fix3-region` = the corner-fixed frontier asset. 177.7s, $0, 26.3K cache-read tokens.
- `or-gemini-3.5-flash`: solid mapping and the sharpest single catch (cf-flux-schnell's 1:1 aspect needs correction), but internally inconsistent — it `hold`s `comparison-d-x4-sharp60` pending Tony QC and then names that same asset `upload_candidate`. 53.8s, unpriced OR spend, 9.3K reasoning tokens.
- `gemini-3.5-flash-lite`: cleanest mechanical verdict mapping but shallowest judgment — picked the baseline `remote-work-home-office-001` as upload candidate despite its own qc_notes saying "do not treat it as the final Adobe Stock submission yet", and marked it `reuse` though the verdict is keep-for-comparison. 32.9s, $0.0053 — cheapest and fastest.

### Cost / latency

| arm | wall s | input tok | output tok | reasoning tok | cache-read | provider cost |
|---|---|---|---|---|---|---|
| gemini-3.5-flash-lite | 32.9 | 36652 | 4030 | 0 | 0 | $0.0053 |
| or-free-nemotron-ultra | 177.7 | 8639 | 4333 | 1562 | 26304 | $0.0000 (not in lane_gate PRICE_TABLE — OpenRouter billing unknown (or-free-* = :free = $0)) |
| or-gemini-3.5-flash | 53.8 | 36626 | 4164 | 9344 | 0 | $0.0000 (not in lane_gate PRICE_TABLE — OpenRouter billing unknown (or-free-* = :free = $0)) |

Isolation audit: zero tool calls, zero permission denials, zero mutating commands, zero write attempts on every arm — the deny-all config held.

Per-arm evidence: `runs/<arm>/` (opencode.json, prompt.md, events.jsonl, artifact.out, verdict.json, run.json).
