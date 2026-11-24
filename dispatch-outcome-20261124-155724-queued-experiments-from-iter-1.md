# Dispatch outcome — inference-provider-watch iter-2 (queued experiments)

Card: `inference-provider-watch` · dispatch `20261124-155724-queued-experiments-from-iter-1` · host idc02 · 2026-11-24

## What was done

Verified live state of every queued experiment, then ran what was runnable.

1. **groq-free group** — Groq re-probed directly (key on idc03 `groq.env`):
   models live (gpt-oss-120b/20b, qwen3.8-27b), TTFT refreshed
   (gpt-oss-120b 272–482ms, gpt-oss-20b 257–426ms, qwen3.8-27b
   726–2849ms), rate limits unchanged (1000 RPD / **8000 TPM** — still
   below one mid-session agent request). iter-1d's "not viable for agent
   loops" verdict stands. The groq deployments are gone from live
   `~/.config/litellm/config.yaml` (iter-1d added them live-only; a later
   deploy from `stacks/idc03/litellm/config.yaml` dropped them) — and the
   same free models now exist as `cf-gpt-oss-120b` / `cf-qwen38-27b`
   Cloudflare routes. Recommendation: do not re-add groq for agent loops;
   it stays a voice-aux/classify single-turn lane.

2. **OpenCode Zen free** — re-benched: 3/4 pass @26s avg, then
   `provider.free-limit` killed the 4th — Zen free is a promo quota
   lane, not always-on.

3. **OpenRouter $10 credit + DeepSeek V4 Flash** — credit confirmed
   purchased: account shows $225 credits/$157.91 used, `:free` cap is
   1000/day (used 1001 today — exhausted). `or-deepseek-v4-flash` paid
   bench ran on the o1–o4 ops corpus: **4/4 pass, $0.0034/run avg,
   29.6s** (total $0.0135). Combined with yesterday's code-corpus run
   (2/2, $0.039): 6/6 tasks, ~$0.05 total — inside the predicted band.
   DeepSeek V4 Flash is verified as the cheap paid code brain.

4. **Mistral Codestral / Cerebras** — BLOCKED: no API keys on any host
   (checked idc02/idc03/tony-dell secrets). Board request raised on the
   card for keys (or a "skip" decision).

5. **Groq/Cerebras TTFT voice-aux** — Groq numbers refreshed (above).
   Cerebras key-blocked with Mistral.

## Bench artifacts

- New config: `~/evals/config.devnest-iter2.yaml` on tony-dell (4 lanes ×
  o1–o4 ops tasks).
- Results: `~/evals/results/20261124_090941_c6e97c.{json,html}` on
  tony-dell — bench 1/4 (real content fails), ds-v4-flash 4/4,
  zen-ds 3/4, cf-gpt-oss-120b 0/4 (CF 429 neuron cap → ~7min retry loops).
- Job record in repo: `docs/ssot/jobs/models/2026-11-24-inference-provider-iter2.yml`.

## Key findings for the living doc

- Every free lane is quota-shaped now: CF 10K neurons/day account-wide
  (gone before the bench ran), Zen promo cap, OR :free 1000/day
  (consumed), Groq 8K TPM/model.
- cf-* fails are NOT fast — opencode retry-loops ~300–417s per task on
  the 429 before exiting 1.
- bench/gemini-3.5-flash-lite went 1/4 today vs 4/4 on 2026-10-25 —
  flagged for watch (quota pressure vs model drift).
- opencode v2.4.1 broke all old `cli_base_args` (`--dir` flag removed);
  working form is positional workspace — patched in the iter-2 config,
  other `config.*.yaml` on tony-dell still carry the dead flag.

## How to verify

- `python3 -c "import yaml; yaml.safe_load(open('docs/ssot/jobs/models/2026-11-24-inference-provider-iter2.yml'))"`
- Card comms has the summary; board request `iter-2-bench-running-two-queued-legs-are-b4e29a` tracks the key asks.
- Bench JSON/HTML on tony-dell `~/evals/results/20261124_090941_c6e97c.*`.

## Follow-ups (not done — gated or out of scope)

- devin-kb `inference-provider-market.md` iter-2 log entry — lives on
  tony-dell outside this worktree; text is in the job record + comms.
- Re-run cf-* lanes after CF neuron reset (00:00 UTC) — pairs with
  `llm-provider-verification-2026-11` step 1.
- Mistral/Cerebras legs await keys (board request pending).

lessons:
- opencode v2.4.1 removed `--dir` from `run`; workspace is now a positional arg — every old `~/evals/config.*.yaml` cli_base_args is silently broken until patched to `[run, --format, json, --model, {model}, --auto, {workspace}, {prompt}]`.
- LiteLLM virtual keys have per-key model allowlists — cf-qwen38-27b 403s on the CHABA key but works on BENCH/ADA; always check `/v1/models` per key before benching a route.
- Cloudflare Workers AI free tier is 10K neurons/day ACCOUNT-wide and shared across all cf-* models — it was exhausted by fleet traffic before this bench ran; cf lanes fail as ~7min retry loops, not fast errors.
- Zen `opencode/*-free` models carry a promo quota (`provider.free-limit` mid-run) — fine for spot checks, not a dependable always-on lane.
- OpenRouter account state is checkable cheaply: `/api/v1/auth/key` (key limits, :free daily used/limit) + `/api/v1/credits` (account balance) — used/limit 1000/1000 proved the $10 uplift without spending anything.
