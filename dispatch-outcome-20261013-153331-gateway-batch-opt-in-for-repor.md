# Dispatch outcome — gateway-batch-opt-in-for-report-extract-aee7d7

Runner: mn01 · Branch: `dispatch/20261013-153331-gateway-batch-opt-in-for-repor` · Commit `3db9f667` (not pushed — dispatch rule)

## What changed

The report/extract/distill batch chain now routes through one shared
Gemini caller, so opting the whole chain onto the idc03 LiteLLM gateway
is a per-job env change with no code edits.

- **NEW `scripts/ada/gemini_rest.py`** — shared `generate()` /
  `generate_json()` over `/v1beta/models/<m>:generateContent`.
  `GEMINI_BASE_URL` default `https://generativelanguage.googleapis.com`;
  accepts bare host (`http://100.102.134.91:4000`) or `/v1beta`-suffixed
  forms. Auth via `x-goog-api-key` (works for Google keys and LiteLLM
  virtual keys). 429/5xx retry with linear backoff (the old distill
  shape); other HTTP errors fail fast with the response body excerpt
  instead of retrying 4× like before.
- **`memory-distill.py`, `distill-devin-bank.py`** — `_gen()` delegates
  to the helper; inline `requests` code removed.
- **`rollup-summaries.py`** — `summarize()` moved off the async
  `google-genai` SDK onto the helper (same env knobs, one less dep).
- **`session-report.py`** — `gemini_json()` delegates to
  `generate_json()`; was already `GEMINI_BASE_URL`-aware but didn't
  normalize a `/v1beta` suffix and had no retries. Keeps its
  `ada-pi-pwa.env` key fallback.
- **Free riders, unchanged:** `memory-distill-benchmark.py` imports
  `memory-distill._gen`; `export-transcripts.py --backfill` spawns
  `session-report.py` — both inherit the env.
- **`docs/ssot/infrastructure/ssot.llm-gateway.yml`** — new
  `batch_opt_in` section: recipe (`GEMINI_BASE_URL` + `GEMINI_API_KEY` =
  `LITELLM_KEY_CHABA`), coverage list, and explicit non-coverage
  (key-probes like gemini-wallet-watch/secrets-inventory stay direct;
  `report-distill.py` is deterministic; `devin-extract-sessions.sh` is
  nlm not Gemini).
- **`docs/ssot/jobs/infrastructure/2026-10-13-gateway-batch-opt-in.yml`** —
  job trail.

## Result

Opt-in recipe (per job env or env_file):
```
GEMINI_BASE_URL=http://100.102.134.91:4000
GEMINI_API_KEY=<LITELLM_KEY_CHABA>   # ~/.config/secrets/litellm-keys.env on idc03
```
Traffic then bills under that virtual key's budget ($5/30d for CHABA),
appears in the spend ledger, and gets the ordered fallbacks. Default
stays direct-Google — nothing was flipped; enabling a live job is a
deploy-gated follow-up decision.

## Verification done

- `py_compile` clean on all touched scripts.
- Helper unit-checked with a stubbed transport: URL building for all
  three base forms, `x-goog-api-key` header, generationConfig JSON mode,
  no-key → None, 400 fails fast (no retry).
- Live probe: `POST :4000/v1beta/models/gemini-3.5-flash-lite:
  generateContent` returns LiteLLM's `token_not_found_in_db` 401 —
  proves the routed Gemini endpoint exists and accepts the
  `x-goog-api-key` shape; a real virtual key wasn't available on mn01.
- `ssot-validate-all.mjs`: both edited/added YAMLs valid (1 pre-existing
  error elsewhere: `jobs/ada/2026-10-13-smoke-tier-to-ada-dev.yml`
  malformed at HEAD — untouched).
- Card progress comment posted.

## To verify after merge

Enable on one batch job (e.g. `devin-bank-distill` on idc02 env_file):
add `GEMINI_BASE_URL` + point `GEMINI_API_KEY` at `LITELLM_KEY_CHABA`,
run the service, then check `/ui` spend ledger on the gateway for a
CHABA line and confirm the journal shows a normal run.
