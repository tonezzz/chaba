# Dispatch outcome — explore-github-copilot-as-llm-backend

## What was done

Evaluated GitHub Copilot Pro (tonezzz; 1500 AI credits/mo, resets
2026-12-01) as a programmatic LLM/agent backend for the infra, per card
spec steps 1–4. All work on tony-omen inside this worktree.

1. **CLI**: `copilot` 1.0.107 already installed (`~/.npm-global`); auth
   via `GH_TOKEN`/`GITHUB_TOKEN` env from
   `~/.config/secrets/github-models.env` (fine-grained PAT — no OAuth).
   `copilot -p` one-shot verified (~8s, agentic footer shows AI Credits).
2. **SDK**: installed `@github/copilot-sdk@1.0.34` in
   `experiments/copilot-sdk/`. Verified `start()` → `listModels()`
   (16 models: claude-sonnet-5.5/5, claude-haiku-5.5/4.5, gpt-6.1-terra,
   gpt-6-luna, gpt-5.6-luna, gpt-5.3-codex, mai-code-1.1/2(-flash),
   grok-4.7/4.6, kimi-k3, gemini-4-hydrogen, auto) → `createSession()` →
   `sendAndWait()` answered "SDK OK" in ~4.7–6.1s on default
   claude-sonnet-5.5.
3. **Credit metering**: `session.rpc.usage.getMetrics()` returns
   per-model token counts + `totalNanoAiu`; `session.rpc.quota.get()`
   returns the live `premium_interactions` budget (entitlement 1500,
   consumed 120 at test time, `usageAllowedWhenExhausted: false`).
   Measured: one trivial turn = `totalNanoAiu` 10.858e9 ≈ **10.9 AIU
   (~0.7% of monthly budget)** — every agentic turn carries ~27k system
   + ~7.7k tool-def tokens (~35k input floor; cache reads reduce
   steady-state).
4. **BYOK**: `SessionConfig.provider {type:"openai", wireApi:
   "completions", baseUrl, apiKey, modelId, wireModel}` — generic
   OpenAI-compatible incl. LiteLLM. Proved end-to-end: request reached
   our LiteLLM (`idc03:4000`) and was rejected only by LiteLLM's own
   $50 budget gate (HTTP 422) — auth/routing/wire all fine. Local
   Ollama BYOK timed out, but environmental: tony-omen Ollama was
   saturated by the idc03 embed lane (hundreds of `/api/embed`/min,
   GPU 88%); even a direct `/v1/chat/completions` curl exceeded 60s.
5. **Verdict**: Copilot Pro is an **agent/IDE surface, not an LLM
   backend**. No raw inference endpoint; SDK/CLI is the only sanctioned
   programmatic path and every call is a full agentic turn (~35k-token
   floor, seconds-scale latency, hard monthly credit cap). It does not
   cover any Ada/litellm model need — those models are already reachable
   cheaper via litellm routes or direct APIs. Niche uses worth keeping:
   `copilot -p` as a GitHub-aware agent lane (is_mcp_enabled,
   cloud_sessions_enabled), PR-review requests, and SDK BYOK as an agent
   *harness* over our own models (inverts the value — not a model
   source). Unofficial api.githubcopilot.com proxies remain ToS-grey —
   not wired anywhere.

## Result / deliverables

- `docs/kb/github-copilot-pro-backend-eval.md` — full eval + verdict.
- `docs/ssot/jobs/experiments/2026-11-25-github-copilot-backend-eval.yml`
  — job record.
- `experiments/copilot-sdk/probe{,2,3-byok,3-ollama,4-byok-trace}.mjs`
  — repro probes (npm i @github/copilot-sdk; GH_TOKEN env required).
- Card comms posted to board-api; committed on dispatch branch
  `dispatch/20261125-074751-context-github-models-service-` (a86988d62d).
  Not pushed, per dispatch rules.

## How to verify

- `cd experiments/copilot-sdk && npm i && GH_TOKEN=$(grep
  GITHUB_PERSONAL_ACCESS_TOKEN ~/.config/secrets/github-models.env |
  cut -d= -f2) node probe2.mjs` → prints models, turn latency, and
  usage/quota JSON.
- KB note has the verdict table and reproduce steps.

## Side findings (not this card's scope)

- LiteLLM CHABA key is over its $50 budget cap — all litellm-routed
  work on that key currently 422s. Pre-existing; may deserve its own
  card if not already known.

lessons:
- @github/copilot-sdk: every sendAndWait is a full agentic turn (~35k-token system+tools floor, ~10.9 AIU measured on a trivial prompt) — useless as a cheap LLM backend; meter via session.rpc.usage.getMetrics()/rpc.quota.get().
- Copilot CLI/SDK auth: GH_TOKEN or GITHUB_TOKEN env with a fine-grained PAT works — no OAuth flow needed.
- SDK BYOK provider {type:"openai", wireApi:"completions"} reaches OpenAI-compatible endpoints (LiteLLM verified); a 422 from the upstream proxy proves transport works — distinguish upstream rejections from wiring failures.
- Local-Ollama BYOK timeouts can be environmental: check ollama journal for inbound requests before blaming the client — tony-omen's embed lane can saturate it.
- Job yml files under docs/ssot/jobs need title/subtitle/icon fields or the pre-commit SSOT validator rejects the commit.
