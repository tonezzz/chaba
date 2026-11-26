# Dispatch outcome — gemini-eval-judge-lane (2026-11-26 22:04 run)

## What changed

Run 1 (session mulberry-soup) had already committed the `config.yaml` change
(+25 lines: `eval-judge` model_name + fail-closed dict-leg fallbacks) and
deployed it to idc03, minted the virtual key, and written most of the client
code before dying mid-verification. Run 2 (this session) verified state,
finished verification, updated SSOT, and committed everything on the dispatch
branch (`d495de11416`).

Committed on `dispatch/20261126-220447-context-gcp-console-quota-capt`:

- `stacks/idc03/litellm/config.yaml` — `eval-judge` → `gemini/gemini-3.5-flash-lite`
  via `GEMINI_API_KEY_PAID`; fallbacks `gemini-3.5-flash-lite →
  ollama-llama32-3b-kkmac → colab-gemma3`, each dict leg with
  `disable_fallbacks:true` so no recursive expansion into free-tier chains.
- `scripts/litellm/eval-budget.py` — capped ledgered client:
  `EVAL_JUDGE_DAILY_MAX=10000`/day, JSONL ledger at
  `~/.local/state/eval-judge/<date>.jsonl`, `service=eval` spend tags,
  parked-with-reason (exit 3, no provider request) on cap.
- `evals/eval-judge/run.py` + `reports/2026-11-26-eval-judge-100.{json,md}` —
  bounded consultant-fixture runner and its first real run.
- `tests/litellm/test_eval_judge_route.py` + `test_eval_budget.py` — 10 tests,
  all pass (incl. OPS-1255 canary regression assert).
- `docs/ssot/infrastructure/ssot.llm-gateway.yml` — `eval-judge` job_class +
  `LITELLM_KEY_EVAL_JUDGE` budget entry with quota-source caveat.
- `docs/ssot/jobs/devnest/2026-11-26-gemini-eval-judge-lane.yml` — full outcome doc.

## Live state on idc03

- LiteLLM proxy restarted with the new config; `eval-judge` registered and its
  fallback chain confirmed in proxy logs.
- Virtual key `eval-judge` verified via `/key/info`: models `['eval-judge']`
  only, $10/30d (reset 2026-12-01), spend $0.00, no dependents. Value lives as
  `LITELLM_KEY_EVAL_JUDGE` in `~/.config/secrets/litellm-keys.env` on idc03 and
  tony-dell (never printed/committed).

## Verification results

- Unit: 10/10 pass. Smoke: 200 + tagged `LiteLLM_SpendLogs` row
  (`service=eval,job=smoke-20261126`). Cap: `EVAL_JUDGE_DAILY_MAX=2` parked the
  next call live — exit 3, `provider_call=false`, no provider request.
- 100-call bounded eval: 100 provider calls, 0 client-visible 429s, 0 errors,
  **100/100 fallback escalations**, agreement 0.60 vs deterministic labels,
  ~101s total, 13,839 tokens, measured spend **$0.00** (all-local path).

## Blocker (needs Tony — board request raised)

`GEMINI_API_KEY_PAID`'s project `gen-lang-client-0854236591` is
**monthly-spend-capped** — every paid `gemini/*` leg returns 429
RESOURCE_EXHAUSTED since ~20:41 +07 (prod `chat` lane degraded; not caused by
this card). The card's motivating quota capture (350k/day, usage 1) was for
project `gen-lang-client-0694401188` — the **archived** ops project, not the
serving one (re-verified live with `scripts/ops/gemini-project-verify.py`).
Real daily headroom on 0854236591 is unverified — Console check needed.

Until the cap lifts, eval-judge calls ride the local fallback (3B judge =
0.60 agreement — not sufficient alone). Re-qualify with
`python3 evals/eval-judge/run.py --calls 100` after the cap resets/lifts;
expect `fallback_escalations=0`.

## How to verify

- `python3 -m pytest tests/litellm/test_eval_judge_route.py tests/litellm/test_eval_budget.py`
- `python3 scripts/litellm/eval-budget.py --status` (cap usage today)
- `curl http://100.102.134.91:4000/v1/models -H "Authorization: Bearer $LITELLM_KEY_EVAL_JUDGE"` on idc03/tony-dell
- Job doc: `docs/ssot/jobs/devnest/2026-11-26-gemini-eval-judge-lane.yml`

lessons:
  - Deploy worktrees inherit live state: run 1 had already deployed config + minted the key before dying — always check SpendLogs/key-info/git log before re-doing infra steps.
  - GCP project spend caps are per-project monthly, separate from per-day request quotas — a 350k/day "usage 1" capture says nothing about the monthly cap; verify WHICH project a key owns (gemini-project-verify.py) before trusting Console quota screenshots.
  - litellm router fallbacks recurse: bare model_name legs re-expand their own chains — dict legs with disable_fallbacks:true are required for a hard fail-closed chain.
  - ssh host alias 'idc03' fails via ProxyJump tony-omen (tcpip forward refused) — use the tailnet IP 100.102.134.91 directly from tony-dell.
