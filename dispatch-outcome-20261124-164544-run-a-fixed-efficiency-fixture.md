# Dispatch outcome — model-efficiency-refresh-deepseek-flint-providers

## What changed / was found

Built a stdlib-only fixed efficiency fixture
(`scripts/bench/model-efficiency.py`, fixture `model-efficiency-v1`: qa /
strict-json / tool-call / thai / ~120-word gen / vision PNG + cold-vs-warm
probes) and ran it across the requested surfaces:

- **Local Ollama (tony-omen):** llama3.2:3b warm p50 0.45s, 5/5 checks —
  best local lane; qwen3:4b HTTP-ok but empty content on every case
  (thinking budget eats small max_tokens); gemma3:4b real vision but
  tools 400 + slow gen.
- **Local Ollama (idc03):** llama3.2:3b correct but CPU-slow (p50 16.4s,
  160s gen); moondream 0/6 checks, 40–80s/call — unusable for agents.
- **Colab burst:** dead — LiteLLM `colab-gemma3` 500s (cannot connect
  :11434), tunnel check 403, all managed runtimes stale.
- **OpenRouter pinned free:** flint / nemotron-3.5-super-vl /
  nemotron-3.5-lightning all HTTP 429 `free-models-per-day-high-balance`
  (1000/day cap, remaining 0); `poolside/laguna-s-2.1:free` delisted
  (404). Flint not re-measurable today.
- **deepseek-flash (NEW, via OR `deepseek/deepseek-v4.1-flash`):** warm
  p50 0.97s, case p50 1.9s, strict-json/tool/vision correct, est
  $0.00028/run; open-ended short prompts returned empty content under
  small max_tokens (reasoning headroom needed). Official
  api.deepseek.com leg skipped — no DEEPSEEK_API_KEY on any host.
- **Gemini gateway vs direct:** `gemini-3.5-flash-lite` p50 0.82s vs
  0.69s, both 5/5 — gateway tax ~0.1s.

OR account: +$0.00069 session spend (two deepseek-flash runs); :free legs
spent $0 on 429s. No secret values in artifacts.

## Deliverables (commit b4c23b34de on dispatch branch)

- `scripts/bench/model-efficiency.py` — reusable fixture harness
- `reports/model-efficiency-2026-11-24.json` — merged raw results
- `reports/model-efficiency-2026-11-24-{local,remote}.json` — raw per-suite
- `reports/model-efficiency-2026-11-24.md` — report + routing notes
- `docs/ssot/jobs/models/2026-11-24-model-efficiency-refresh.yml` — job record

## Result / how to verify

No model routing was changed (card gate: verifier review first). Verify
with `python3 -c "import json;d=json.load(open('reports/model-efficiency-2026-11-24.json'));print(len(d['runs']))"`
(14 runs) or re-run `python3 scripts/bench/model-efficiency.py --suite
local --only llama3.2`. Card comms posted with the same summary.

lessons:
- idc03 Ollama is NOT on 127.0.0.1 — use http://100.102.134.91:11434/v1 (127.0.0.1 refuses).
- Reasoning models (qwen3:4b, deepseek-v4.1-flash, moondream-style small budgets) return empty content when max_tokens is tiny; the fixture needs per-target token headroom or thinking-off config to measure them fairly.
- OR :free daily cap (1000/day account-wide) was already exhausted by fleet traffic — :free legs can only be measured right after the UTC reset.
- `poolside/laguna-s-2.1:free` is delisted on OpenRouter (404) — check /api/v1/models before pinning :free ids.
