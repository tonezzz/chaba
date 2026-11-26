# LiteLLM Model List: Verification, Update, and Maintenance (2026-11-20)

**Scope:** idc03 LiteLLM gateway (single LLM API point, tailnet `http://100.102.134.91:4000`)  
**Canonical config (repo):** `chaba/stacks/idc03/litellm/config.yaml`  
**Live config (idc03):** `~/.config/litellm/config.yaml` (deployed via `stacks/idc03/litellm/deploy.sh`)  
**Routing/ops SSOT:** `chaba/docs/ssot/infrastructure/ssot.llm-gateway.yml`, `ssot.model-routing.yml`

## What "the model list" is
LiteLLM serves a catalog of **routes** (`model_list[].model_name`). Callers use route names (real model names like `gemini-3.5-flash`, or job-class aliases like `tool-call`, `chat`, `summary`, `embedding`, `vision`) and LiteLLM applies ordered fallbacks, spend/keys, and provider routing per `router_settings`.

- `/v1/models` = what the proxy currently advertises (requires an authorized virtual key).
- `/health/liveliness` = gateway process health (does not prove every upstream works).
- Functional truth requires probing: a route can be listed but fail upstream (deprecated model, invalid key, quota, tunnel/admission down).

## Verification procedure (safe, evidence-first)
1. **Health:** `GET /health/liveliness` → 200.
2. **Catalog parity:** compare repo `config.yaml` model names vs live `GET /v1/models` (authorized). Repo and live config files should match (hash/check).
3. **Functional probe per route** (cheap):
   - Chat routes: minimal `POST /v1/chat/completions` (tiny prompt, low max_tokens).
   - Embedding routes: `POST /v1/embeddings` (`input:"ping"`), confirm vector dims.
   - Skip/cost-gate image-gen routes unless explicitly needed.
   - Distinguish **catalog/config breakage** (404/410/bad model/invalid key) from **infra/transient** (tunnel/shim admission 503, colab offline, local cold-start timeout, 429 quota).
4. **Config sanity:** unique route names, every fallback group/target exists in `model_list`, router chains make sense for the job class.
5. **Consumer surfaces:** update derived/consumer allowlists when names change (opencode provider maps, lane/profile `model.allowed`, scripts/bridges with hardcoded allowlists, SSOT docs/inventory).

## 2026-11-20 verification summary (idc03)
- **52 routes served** initially, identical to repo config. Live gateway redeployed after fixes; **49 unique routes** served.
- **Answered (chat/embed):** core Gemini 2.5/3.5 paid+OR routes, 3.5-free routes, job-class aliases (`tool-call/chat/summary/voice-aux/classify/bench/embedding/image/vision`), OR strong/bench routes (`or-claude-fable-5.1`, `or-gemini-3.1-pro-preview`, etc.), most OR `:free` routes, CF `cf-llama-70b/cf-gpt-oss-120b/cf-mistral-small/cf-embed-m3`. Local idc03/tony-dell ollama routes (`chat-local`, `ollama-llama3.2`, `ollama-moondream`, `ollama-nomic-embed`, `ollama-qwen7b`, `vision`) responded on longer waits (capacity/cold-start), not missing.
- **Catalog/upstream breakage fixed:**
  - Cloudflare Workers AI (deprecated 2026-11-20, 410): `@cf/meta/llama-3.1-8b-instruct-fp8`, `@cf/qwen/qwen3-30b-a3b-fp8`, `@cf/nvidia/nemotron-3-120b-a12b` → repointed/renamed to `cf-llama4-scout` (`@cf/meta/llama-4-scout-17b-16e-instruct`, 131k), `cf-qwen38-27b` (`@cf/qwen/qwen3.8-27b`, 262k, reasoning), `cf-gemma4-26b` (`@cf/google/gemma-4-26b-a4b-it`, 256k, reasoning). Replacements verified against the live CF model catalog and probed directly on CF.
  - OpenRouter: `or-free-north-code` removed (404, no provider serves it).
  - Gemini free tier (2.5 family): `gemini-2.5-flash-free` / `gemini-2.5-flash-lite-free` removed (404 "no longer available to new users" on free key). 2.5 **paid** and 3.5 **free** routes remain healthy; fallbacks adjusted.
- **Infra/availability (not removed):** kk-mac ollama routes 503 `admission denied: heartbeat_stale+disk_low` (kkmac tunnel/admission shim inactive); `colab-gemma3` 500 (ephemeral tunnel down). These are host-state issues, not model-name errors.
- **Key/upstream issues (kept, noted):** `or-free-gemma31b` and `or-gemini-embedding-2` returned 400 invalid-key/provider errors on the current OR key; `embedding` job-class remains healthy via `gemini-embedding-2` fallback. `gemini-3.1-pro-free` hit 429 quota at probe time.
- **Image-gen routes** (`gemini-3.1-flash-image`, `gemini-3.1-flash-lite-image`, `or-gemini-3.1-flash-image`) intentionally not probed (cost).

## Artifacts updated (this pass)
- `chaba/stacks/idc03/litellm/config.yaml` and live `idc03:~/.config/litellm/config.yaml` (restarted, healthy).
- `chaba/docs/ssot/infrastructure/ssot.llm-gateway.yml` (`free_lane_aliases` / removed_2026_11_20).
- Local opencode map `~/.config/opencode/opencode.json` (replaced removed CF/north-code entries).
- Opencode-lane profiles: removed `litellm/or-free-north-code` from `evals/opencode-lane/profiles/{info-find,ops-readonly,ssot-research}/profile.yml`.
- Active consumers: `scripts/colab/packs/cline-kanban-nest-bridge/bridge.py`, `scripts/bench/card-judgment/distill.py`, `stacks/idc02/jack-ide/opencode/opencode.json`.

## Gotchas / lessons
- **Listed ≠ working:** always do a small functional probe; deprecations (CF 410, OR 404) and free-tier eligibility (Gemini 404 "no longer available to new users") can appear without config changes.
- **Distinguish failure classes:** route/model gone or key invalid vs admission/tunnel down vs quota/rate-limit vs cold-start timeout. Only the first class means the catalog entry is wrong.
- **Reasoning models:** keep `merge_reasoning_content_in_choices`/caps aligned with upstream behavior for clients that expect plain `content`.
- **Multiple manual surfaces drift:** runtime config, SSOT docs, opencode provider maps, profile allowlists, and script allowlists must move together (see `scripts/devnest/sync-opencode-models.py`, card `model-route-registration-unify` / OPS-1020).
- **Embeddings are space-sensitive:** do not silently substitute a different embedding space for retrieval; keep fallback chains within the intended vector space.

## Suggested follow-ups
- Re-probe newly repointed CF routes (`cf-qwen38-27b`, `cf-gemma4-26b`, `cf-llama4-scout`) through LiteLLM after neuron/rate pressure clears (direct-CF probes were healthy).
- Investigate/fix `or-free-gemma31b` and `or-gemini-embedding-2` key validity, or prune/annotate them if intentionally unusable.
- Restore kk-mac tunnel/admission health if kk-mac ollama routes are needed.
- Consider a single declarative model-catalog SSOT that generates/validates runtime config + opencode maps + profile allowlists (see recommendation below).
