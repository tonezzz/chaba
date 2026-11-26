# Dispatch outcome — bench gemini-3.8-live-extended-thinking vs 3.8-live pin

Card: `gemini-38-live-extended-thinking-bench-2026-11-26` (ADA-1446)
Branch: `dispatch/20261126-181728-bench-gemini-3-8-live-extended` — commit `5d3affcc13` (not pushed)

## Result

**Verdict: keep `gemini-3.8-live` pinned.** Extended-thinking passed every
gate except latency: ~75% slower round-trip (10.9s vs 6.2s mean), same WER
(0.01), slightly better tool coverage (8e/6p/0n vs 7e/4p/3n), barge-in and
9-turn soak green on both. Its conversational fillers + mandatory
thinkingLevel/NON_BLOCKING protocol cost more than the marginal gain on
simple HA commands — matches its SSOT "pilot only" note.

## What changed

- `scripts/voice-bench/combos.yml` — new `gemini-live-extended-thinking`
  combo (`gemini_model`, `thinking_level: LOW`); loader + `result_doc` carry
  both fields (`lib.py`).
- `scripts/voice-bench/adapters.py` — `gemini_live` resolves model from
  combo > env > default; thinking-mode auto-detect emits
  `generationConfig.thinkingConfig.thinkingLevel` and
  `behavior: NON_BLOCKING` on all declarations; completion gates on
  `interactionStatus IDLE` (turnComplete = utterance end only).
- `scripts/voice-bench/live_probes.py` (new) — committed barge-in + soak
  probes, quiescence-based turn detection (aborted turn closes
  turnComplete+IDLE; naive done-checks false-trigger).
- `docs/ssot/jobs/voice/2026-11-26-gemini-38-live-extended-thinking-eval.yml`
  — full gate table vs the 2026-11-24 baseline; `ssot.gemini-models.gemini-3.yml`
  note updated; `reports/voice-fallback/{LATEST,trend}.md` regenerated.
- Result JSONs force-added under `scripts/voice-bench/results/` (gitignored
  dir, tracked-file precedent).

## Gotchas hit

- Paid Gemini keys (`gemini-api-key.env`, `chaba-paid.env`) are over the
  shared project's monthly spend cap — all 429 RESOURCE_EXHAUSTED. Bench
  ran on `ada-lab.env` GEMINI_API_KEY. Flagged as a follow_up in the job doc.
- `ttfa_ms` on the thinking model is not comparable to the 306ms baseline
  metric (anchor collapses to ~0ms); used `total_ms` for the latency gate.
- `interactionStatus` arrives both top-level and inside `serverContent`;
  toolCall-only turns never emit turnComplete — need the 4s idle fallback.

## Verify

- `git show 5d3affcc13` — all artifacts on the dispatch branch.
- Job doc has the per-fixture table pointers + raw JSON filenames.
- Reproduce: `source ~/.config/secrets/ada-lab.env; cd scripts/voice-bench
  && /tmp/vb-venv/bin/python bench.py --combo gemini-live-extended-thinking`.

lessons:
- gemini-3.8-live-extended-thinking needs thinkingConfig.thinkingLevel in setup (minimal is rejected, ws close 1007) and NON_BLOCKING on every function declaration; interactionStatus IDLE — not turnComplete — ends the request.
- turnComplete alone truncates extended-thinking exchanges exactly like the old 3.8-live two-phase bug; barge-in probes must wait for post-barge turnComplete + IDLE + audio + transcript quiescence or they false-pass.
- The shared paid Gemini project (gen-lang-client-0854236591) is over its monthly spend cap as of 2026-11-26 — use ~/.config/secrets/ada-lab.env GEMINI_API_KEY for Live benches until Tony raises it.
- ttfa_ms anchored to first inputTranscription is meaningless on the thinking model (final transcript + filler audio arrive in the same batch); gate on total_ms instead.
