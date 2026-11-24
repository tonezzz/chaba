# Model efficiency refresh — fixed fixture 2026-11-24

Card: `model-efficiency-refresh-deepseek-flint-providers` (OPS-0878)
Fixture: `model-efficiency-v1` — `scripts/bench/model-efficiency.py`
Raw JSON: `reports/model-efficiency-2026-11-24.json` (+ `-local.json`, `-remote.json`)
Job record: `docs/ssot/jobs/models/2026-11-24-model-efficiency-refresh.yml`

## What was measured

One fixed case suite per target: `qa_japan`, `json_extract` (strict JSON),
`tool_weather` (OpenAI tools / Gemini functionDeclarations), `thai_capital`,
`gen_bottle` (~120-word generation), `vision_colors` (64×64 red/blue PNG, only
when the target declares vision). Cold = first call after `ollama stop` for
local legs / first call of the run for API legs; warm = 2 repeat `qa_japan`
probes. Errors/429s, token usage, check pass rate, est. cost, license/data
policy, and hardware fit are recorded per target. No secret values in any
artifact — env-var names only.

## Results

| alias | provider/model | status | cold s | case p50 s | warm p50 s | tokens | err | checks | est $ |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ollama-omen-llama3.2-3b | local Ollama | ok | 14.7 | 3.6 | 0.45 | 525 | 0 | 5/5 | 0 |
| ollama-omen-qwen3-4b | local Ollama | ok* | 17.0 | 23.3 | 11.0 | 774 | 0 | 0/5 | 0 |
| ollama-omen-gemma3-4b | local Ollama | partial | 52.0 | 40.4 | 0.60 | 676 | 1 | 5/6 | 0 |
| ollama-idc03-llama3.2-3b | local Ollama | ok | 34.1 | 16.4 | 1.9 | 519 | 0 | 5/5 | 0 |
| ollama-idc03-moondream | local Ollama | partial | 83.7 | 51.9 | 38.1 | 1163 | 1 | 0/6 | 0 |
| colab-gemma3 | LiteLLM→Colab T4 | all_failed | — | — | — | 0 | 5 | 0/5 | 0 |
| or-flint-v1.0-free | OpenRouter :free | all_failed | — | — | — | 0 | 5×429 | — | 0 |
| or-nemotron-3.5-super-vl-free | OpenRouter :free | all_failed | — | — | — | 0 | 6×429 | — | 0 |
| or-nemotron-3.5-lightning-free | OpenRouter :free | all_failed | — | — | — | 0 | 5×429 | — | 0 |
| or-laguna-s-2.1-free | OpenRouter :free | all_failed | — | — | — | 0 | 5×404 | — | 0 |
| **deepseek-flash** | OR `deepseek/deepseek-v4.1-flash` | ok | 2.2 | 1.9 | 0.97 | 1174 | 0 | 3/6 | $0.00028 |
| deepseek-flash-official | api.deepseek.com | no_credentials | — | — | — | — | — | — | — |
| gemini-3.5-flash-lite-gateway | LiteLLM→Gemini | ok | 0.80 | 0.82 | 0.78 | 359 | 0 | 5/5 | metered |
| gemini-3.5-flash-lite-direct | Gemini direct | ok | 0.66 | 0.69 | 0.78 | 357 | 0 | 5/5 | metered |

`*` qwen3:4b HTTP-ok on every call but returned **empty content** on all 5
checks — its thinking budget consumes the small `max_tokens` before any
answer text (verified: 64 completion tokens, empty content, even with
`think:false` / `reasoning_effort:low` via OpenAI-compat). Treat as
unsuitable for small-budget lanes unless thinking is disabled natively.

## Findings

- **DeepSeek V4.1 Flash (`deepseek-flash`) is real and cheap.** Via
  OpenRouter `deepseek/deepseek-v4.1-flash` (the card's requested alias):
  warm p50 **0.97 s**, strict-JSON / tool-call / vision all correct, est.
  **$0.00028 per fixture run** (~$0.14/M in, $0.42/M out). Open-ended short
  prompts (`qa_japan`, `thai_capital`, `gen_bottle`) returned empty content
  under reasoning defaults — same small-budget starvation as qwen3:4b;
  `reasoning_effort=low` was set and structured/tool/vision still passed.
  Needs larger `max_tokens` headroom for chat lanes. Official
  `api.deepseek.com` leg is **credential-blocked**: no `DEEPSEEK_API_KEY`
  on tony-omen/idc03/tony-dell.
- **OpenRouter :free is quota-dead today, not model-dead.** Every pinned
  free leg returned HTTP 429 `free-models-per-day-high-balance`
  (limit 1000/day, remaining 0). `poolside/laguna-s-2.1:free` is also
  **delisted** (404 "no provider serves this model anymore") — drop it
  from any allowlist. Flint could not be re-measured today; prior
  scorecard stands (comp 85.0, p50 1.3 s).
- **Colab burst is down.** LiteLLM `colab-gemma3` → 500
  `Cannot connect to host …:11434`; `colab_tunnel_check` 403 and all
  managed runtimes are stale. No fresh T4 to burst into.
- **Gemini gateway ≈ direct.** `gemini-3.5-flash-lite` via LiteLLM
  (LITELLM_KEY_CHABA) p50 0.82 s vs direct paid key 0.69 s — gateway tax
  ~0.1 s, both 5/5 checks. Gateway remains the right call for routing/
  spend-ledger reasons, not latency.
- **Local Ollama:** omen `llama3.2:3b` is the best local lane (warm
  0.45 s, 5/5, cold 14.7 s incl. load). idc03 CPU `llama3.2:3b` is
  correct but slow (p50 16.4 s, 160 s gen) — batch-only. `moondream`
  (idc03 vision) is unusable for agent lanes (0/6 checks, ~40-80 s/call).
  `gemma3:4b` does real vision (107 s cold-ish call, correct colors) but
  rejects the tools payload (HTTP 400) and is slow on gen.

## Cost / quota

- OR account: $225 credits, usage $157.9105 → $157.9112 (**+$0.00069**
  this session = two deepseek-flash runs; :free legs spent $0 because
  they 429'd). Key self-limit $1/week, $0.689 remaining.
- DeepSeek official API would be peak $0.30/M in / $1.20/M out — not
  measured (no key).
- Gemini legs are metered paid; spend lands on `LITELLM_KEY_CHABA` /
  `GEMINI_API_KEY_PAID` (not itemized here).

## Routing impact — NONE applied

Per card: model routing updates wait for verifier review. Candidate notes
for the reviewer: `deepseek-flash` (OR paid V4.1 Flash) is a strong cheap
code/vision lane once reasoning headroom is budgeted; OR :free needs the
daily cap reset before Flint/nemotron re-measurement; `laguna-s-2.1:free`
should be removed; `colab-gemma3` stays dead until a fresh T4 registers.
