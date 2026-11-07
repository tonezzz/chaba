# AI Studio eval lane (Google AI Pro)

OPS-1048 finding #4. The AI Pro subscription raises quotas ONLY inside the
AI Studio web UI (Playground + Build) — never the API keys.

## Use it for

- Model-selection benches before wiring a model into LiteLLM chains
  (gemini-3.5-flash-lite vs alternatives, paid_frontier candidates).
- Quick prompt iteration for jev-routing/classify prompts — free on
  subscription quota, no LITELLM_KEY_BENCH burn.
- Trying premium models not on the fleet keys (Gemini 4 Argon,
  Nano Banana 2.1, Lyria 3.5).

## Rules

- In Studio, choose the "Google AI" billing option (not "Pay per
  request") so usage burns subscription quota, not paid credits.
- Winners still ship through LiteLLM/API keys — Studio quota never
  reaches the fleet.
- Record eval outcomes on the relevant card; the lane is desk-research
  only, no DevNest code.
