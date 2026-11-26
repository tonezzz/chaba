# GitHub Copilot Pro as LLM/agent backend — evaluation

Date: 2026-11-25 · card `explore-github-copilot-as-llm-backend` (SYS-1085) · host tony-omen

## Verdict

**Copilot Pro is an agent/IDE surface, not an LLM backend.** It does not
cover any Ada/litellm model need. The only sanctioned programmatic path is
the Copilot CLI + `@github/copilot-sdk` (JSON-RPC over a spawned CLI
runtime); there is no raw chat-completions endpoint, and the unofficial
`api.githubcopilot.com` proxies are ToS-grey — do not wire them into
litellm/Ada.

## What was verified live (tony-omen, 2026-11-25)

- `copilot` CLI 1.0.107 at `~/.npm-global/bin/copilot`; auth via
  `GH_TOKEN`/`GITHUB_TOKEN` env from `~/.config/secrets/github-models.env`
  (fine-grained PAT, no OAuth dance). `copilot -p` one-shot works.
- `@github/copilot-sdk` 1.0.34 (`npm i` in a scratch dir):
  - `client.start()` → `listModels()` → 16 models: `auto`,
    `claude-sonnet-5.5`, `claude-sonnet-5`, `claude-haiku-5.5/4.5`,
    `gpt-6.1-terra`, `gpt-6-luna`, `gpt-5.6-luna`, `gpt-5.3-codex`,
    `mai-code-1.1-flash`, `mai-code-2(-flash)`, `grok-4.7/4.6`,
    `kimi-k3`, `gemini-4-hydrogen`.
  - `createSession()` + `sendAndWait("Reply with exactly: SDK OK")` →
    answered in ~4.7–6s on default `claude-sonnet-5.5`.
  - Metering is precise and scriptable:
    `session.rpc.usage.getMetrics()` → per-model token counts +
    `totalNanoAiu`; `session.rpc.quota.get()` → live
    `premium_interactions` budget (entitlement 1500 AI credits/mo,
    consumed/remaining/ reset 2026-12-01).
- Credit burn: one trivial turn ("reply OK", 4 in / 7 out tokens)
  cost `totalNanoAiu = 10,858,000,000` ≈ **10.9 AIU (~0.7% of the monthly
  1500-credit budget)** because every agentic turn carries a ~27k-token
  system prompt + ~7.7k tokens of tool definitions (~35k input tokens
  before caching). Steady-state turns are cheaper via prompt-cache reads,
  but the floor per call is far above a raw completion.
- BYOK works as designed: `SessionConfig.provider = {type:"openai",
  wireApi:"completions", baseUrl, apiKey, modelId, wireModel}` — generic
  OpenAI-compatible, so LiteLLM `/v1` is a valid target. Verified the
  request reaches our LiteLLM (`idc03:4000`) end-to-end: it was rejected
  only by LiteLLM's own budget gate (`422 Budget has been exceeded`,
  CHABA key at $50 cap) — auth, routing, and wire format all fine.
  BYOK session against local Ollama timed out, but that was environmental:
  tony-omen's Ollama was saturated by the idc03 embed lane (hundreds of
  `/api/embed` calls/min, GPU 88%) and even a direct
  `/v1/chat/completions` curl exceeded 60s. Not a Copilot limitation.

## Why it doesn't fit Ada/litellm needs

- No raw inference endpoint — every call is a full agentic session turn
  (~35k-token floor, tool definitions, system prompt). Using it as a
  cheap text model would burn the 1500-credit budget in a few hundred
  calls and still pay agent overhead per call.
- Latency floor is agent-turn latency (seconds), not completion latency.
- Billing is per-account AI credits with a hard monthly cap and
  `usageAllowedWhenExhausted: false` — no pay-per-use overflow on Pro.
- The models it does serve (Claude/GPT/Gemini/Grok/Kimi frontier set)
  are reachable cheaper through existing litellm routes
  (gemini-*, or-*, cf-*) or direct APIs.

## Where it IS useful for us

- `copilot -p "<prompt>"` as an occasional GitHub-aware agent lane
  (repo context, PR ops, `is_mcp_enabled` so it can call our MCP
  servers, `cloud_sessions_enabled`).
- Copilot code review / `copilot-pull-request-reviewer` on PRs
  (REST-requested, verified earlier on chaba PR#80).
- SDK BYOK inverts the value: Copilot's agent *harness* over our own
  LiteLLM/Ollama models — plausible future experiment if we ever want
  Copilot's UX/tools on local models, but not a model source.
- If we ever want programmatic frontier-model calls within ToS, the SDK
  is the door — just budget ~10 AIU per trivial turn and meter via
  `rpc.quota.get()`.

## Reproduce

Probes live in this worktree: `experiments/copilot-sdk/probe.mjs`,
`probe2.mjs` (usage/quota metering), `probe3-byok.mjs` (LiteLLM BYOK),
`probe4-byok-trace.mjs` (event-traced BYOK). Requires
`GH_TOKEN`/`GITHUB_TOKEN` env and `npm i @github/copilot-sdk`.

## Open

- Whether `copilot` CLI's own MCP config could give dispatch lanes a
  cheap GitHub-ops tool — worth a card only if a concrete need appears.
- LiteLLM CHABA key budget is exhausted ($50 cap) — separate issue,
  affects all litellm-routed work, not Copilot.
