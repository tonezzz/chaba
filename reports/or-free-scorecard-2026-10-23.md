# OR :free rotation scorecard — 2026-10-23 11:04:29 +0700

Shape: jev-bench/bench-hermes arms vs OR /chat/completions, model
pinned per row. `openrouter/free` row = auto-router (resolved_models
shows what it actually picked). Dead ids = in the ghostroute
allowlist but absent from the live OR :free shelf today.

## Scorecard

| model | tc_native | tc_prompted | routing | reasoning | json_strict | p50 s | err | tps |
|---|---|---|---|---|---|---|---|---|
| openrouter/free | 100.0 | 60.0 | 66.7 | 100.0 | 50.0 | 2.6 | 0 | 42.2 |
| google/gemma-4-26b-a4b-it:free | 0.0 | 0.0 | 0.0* | 0.0* | 0.0 | - | 26 | - |
| google/gemma-4-31b-it:free | 0.0 | 0.0 | 0.0* | 0.0* | 0.0 | - | 26 | - |
| nvidia/nemotron-3.5-lightning:free | 100.0 | 60.0 | 91.7 | 100.0 | 75.0 | 4.1 | 0 | 72.7 |
| nvidia/nemotron-3.5-super-vl:free | 80.0 | 100.0 | 100.0 | 100.0 | 100.0 | 1.9 | 0 | 68.7 |
| nvidia/nemotron-3-ultra-550b-a55b:free | 80.0 | 60.0 | 100.0 | 100.0 | 75.0 | 4.8 | 0 | 28.1 |
| cohere/north-mini-code:free | 100.0 | 0.0 | 100.0 | 100.0 | 100.0 | 2.3 | 0 | 52.3 |
| thinkingmachines/inkling-small:free | 0.0 | 0.0 | 0.0* | 0.0* | 0.0 | - | 26 | - |
| thinkingmachines/inkling:free | 0.0 | 0.0 | 0.0* | 0.0* | 0.0 | - | 26 | - |
| xingchen-agi/xing4.0-29b-a4b:free | 40.0 | 20.0 | 16.7 | 16.7 | 25.0 | 4.5 | 22 | 33.7 |
| recursive/flint-v1.0:free | 100.0 | 80.0 | 100.0 | 100.0 | 75.0 | 1.3 | 0 | 76.6 |
| dots-studio/dots-3-note-preview:free | 100.0 | 100.0 | 100.0 | 83.3 | 50.0 | 2.8 | 0 | 60.9 |
| liquid/lfm-2.5-2.6b:free | 100.0 | 0.0 | 41.7 | 83.3 | 75.0 | 22.9 | 0 | 6.6 |
| nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free | 40.0 | 60.0 | 58.3 | 16.7 | 50.0 | 1.3 | 0 | 42.6 |
| nvidia/nemotron-3-super-120b-a12b:free | 0.0 | 0.0 | 0.0* | 0.0* | 0.0 | - | 26 | - |
| nvidia/nemotron-3.5-content-safety:free | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 2.4 | 5 | 38.5 |
| poolside/laguna-s-2.1:free | 100.0 | 100.0 | 100.0 | 66.7 | 100.0 | 3.3 | 0 | 15.6 |
| poolside/laguna-xs-2.1:free | 40.0 | 60.0 | 58.3 | 50.0 | 0.0 | 0.8 | 11 | 44.1 |
| google/gemini-2.5-flash-lite | 0.0 | 0.0 | 0.0* | 0.0* | 0.0 | - | 26 | - |
| google/gemini-2.5-flash | 0.0 | 0.0 | 0.0* | 0.0* | 0.0 | - | 26 | - |
| google/gemini-3.5-flash-lite | 0.0 | 0.0 | 0.0* | 0.0* | 0.0 | - | 26 | - |

(* = run aborted early by circuit breaker — 6 consecutive
  failures; score is over attempted cases only)

## Dead ids still in the ghostroute allowlist

- `openrouter/qwen/qwen3.8-27b:free` — not on the live :free shelf; drop from rotation
- `openrouter/inclusionai/ling-3.0-flash-sante:free` — not on the live :free shelf; drop from rotation
- `openrouter/inclusionai/ling-3.0-flash-fin:free` — not on the live :free shelf; drop from rotation
- `openrouter/stealth/space-bunny-alpha:free` — not on the live :free shelf; drop from rotation
- `openrouter/apodex/apodex-1.1-mini:free` — not on the live :free shelf; drop from rotation
- `openrouter/inclusionai/ling-3.1-flash:free` — not on the live :free shelf; drop from rotation
- `openrouter/google/lyria-3-pro-preview:free` — not on the live :free shelf; drop from rotation
- `openrouter/minimax/minimax-m3.1-flash:free` — not on the live :free shelf; drop from rotation

## openrouter/free resolved to

- `cohere/north-mini-code:free`
- `dots-studio/dots-3-note-preview:free`
- `liquid/lfm-2.5-2.6b:free`
- `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`
- `nvidia/nemotron-3-ultra-550b-a55b:free`
- `nvidia/nemotron-3.5-content-safety:free`
- `nvidia/nemotron-3.5-lightning:free`
- `nvidia/nemotron-3.5-super-vl:free`
- `poolside/laguna-s-2.1:free`
- `poolside/laguna-xs-2.1:free`
- `recursive/flint-v1.0:free`

