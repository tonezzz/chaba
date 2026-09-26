---
category: research
status: living — re-check before each re-research pass
---

# Google AI / Gemini landscape for the estate

Compiled 2026-09-26 from ai.google.dev + Google blog + ModelCap. Purpose:
map Google API models to places they could raise our efficiency; revisit
before committing anything.

## Naming decoder (Tony's question)

| Codename | Real model ID | What it is |
|---|---|---|
| **Nano Banana** (original) | `gemini-2.5-flash-image` | legacy image gen/edit — Google recommends migrating off |
| **Nano Banana 2** | `gemini-3.1-flash-image` | image workhorse: 4K, multi-ref, search-grounded |
| **Nano Banana 2 Lite** | `gemini-3.1-flash-lite-image` | fastest/cheapest image model, 0.5K-1K |
| **Nano Banana Pro** | `gemini-3-pro-image` | top-quality image, pro control |
| **"Gravity"** | — not a model | It's ModelCap's benchmark score column. |
| **Gemini Omni Flash** | `gemini-omni-1.1-flash` | video generation + conversational video editing |

## Current text/multimodal line (Gemini API)

| Model | ID | $/1M in → out | Note |
|---|---|---|---|
| Gemini 3.8 Flash | `gemini-3.8-flash` | $0.75 / $3.75 | current stable flagship-flash (supersedes 3.5/3.6/3.7) |
| Gemini 3.5 Flash-Lite | `gemini-3.5-flash-lite` | $0.30 / $2.50 | cheap high-volume |
| Gemini 3.1 Flash-Lite | `gemini-3.1-flash-lite` | $0.25 / $1.50 | stable, even cheaper |
| Gemini 3.1 Pro | `gemini-3.1-pro-preview` | $2 / $12 | preview, complex reasoning |
| Gemini 2.5 Flash | `gemini-2.5-flash` | ~$0.30 | previous gen, still fine |

All 1M context, 64k output.

## Voice/audio/video specialist models

| Model | ID | Fit for us |
|---|---|---|
| Gemini 3.1 Flash Live | `gemini-3.1-flash-live-preview` | **Ada's realtime voice** — we already run Live API; upgrade candidate |
| Gemini 3.5 Live Translate | `gemini-3.5-live-translate-preview` | **70+ languages real-time speech→speech** — bilingual EN/TH household, very on-target |
| Gemini 3.5 Transcribe | `gemini-3.5-transcribe` (+`-live`) | yomi voice-message transcription |
| Gemini 3.1 Flash TTS | `gemini-3.1-flash-tts-preview` | Ada voice upgrade path (already have ada_set_voice) |
| Veo / Omni | `gemini-omni-1.1-flash` | video gen — low priority |

## Where we already use Google

- **Ada voice**: Gemini Live API session (`realtime_provider.py`)
- **yomi vision**: `gemma-4-31b-it` / `gemma-4-26b-a4b-it` LOCAL (not API) — media descriptions
- **yomi summaries**: `daily-summary.mjs` via Gemini API (check which model — likely 2.5-era)
- **NotebookLM**: MCP integration exists

## Efficiency candidates (ranked)

1. **`gemini-3.1-flash-live` for Ada** — newer Live model; check pricing/latency vs current. If Ada's Live model is 2.5-era this is a straight upgrade.
2. **`gemini-3.5-live-translate`** — real-time speech-to-speech TH↔EN; household fit (KK speaks Thai).
3. **`gemini-3.1-flash-lite` as the cheap triage brain** — classify idea bursts, summarize job outputs, pre-filter pending answers. $0.25/1M in — basically free at our volume; could run inside `digest-to-mddb` and the watch to auto-summarize job tails.
4. **`gemini-3.5-transcribe`** for yomi audio/voice notes → text before digest.
5. **Nano Banana 2 Lite** — cheap image path if we want Ada/Chaba to generate UI mockups or analyze LINE images (better than local gemma vision? — test).

## Cost guardrail note

Google quota burns are a known pain point (see `ssot.learning.idc01-warp-tailscaled` era + the `1f33052` commit reverting google_search). Any new API surface should get a rate cap from day one.

## Re-research checklist (next pass)

- [ ] Which Live model does Ada actually run today? Compare vs 3.1-flash-live.
- [ ] Confirm `daily-summary.mjs` model; consider moving yomi summarize to `gemini-3.1-flash-lite` or keep local gemma.
- [ ] Nano Banana 2 Lite vs local `gemma-4-31b` for image understanding — run a small bake-off.
- [ ] Check Live Translate availability/quota in our region (TH).
- [ ] Embedding model: does MDDB use gemini embeddings? If not, what does it use — and is text-embedding worth adding?
