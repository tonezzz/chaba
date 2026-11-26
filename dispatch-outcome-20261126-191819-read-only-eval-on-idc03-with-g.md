# Dispatch outcome — gemini4-interactions-text-agent-eval-2026-11-26

## What was done

Read-only eval on idc03 with `GEMINI_API_KEY_MICHAEL` (free tier; paid project
verified still spend-capped). Installed `google-genai` 3.6.1 in a throwaway
`/tmp/gemini-eval-venv`, built a fixed 8-task tool+cross-turn-recall fixture
(`scripts/bench/gemini-interactions-eval.py`, deterministic fake tools), and ran
it across Interactions-API lanes (`api_version="v1beta"`):

- stateful `previous_interaction_id` chaining
- stateless full step-history resend
- `models.generate_content` baseline (current 3.x path)

## Result

- **gemini-4 could not be evaluated — quota, not code.** hydrogen: 503
  high-demand then 429 "20 requests/day free tier" (exhausted);
  neon/argon/carbon: 429 "limit: 0" on free tier; `GEMINI_API_KEY_PAID`:
  still 429 monthly spending cap (re-verified this session).
- On the models that do work (gemini-3.5-flash-lite, gemini-3.1-flash-lite via
  Interactions API): adjusted scores **1.000 stateful / 1.000 stateless /
  0.975 / 1.000**; generateContent lane scored 1.000 on completed tasks but
  hit free-tier 429s mid-run.
- Mechanics verified: tool loop (`requires_action` → `function_call` →
  `function_result`), chaining, and the Gemini-3 rule that replayed
  function-call history must carry thought-step `signature` verbatim
  (else 400). `usage.total_input_tokens` grows with context in BOTH modes —
  stateful saves request payload (1–2 steps vs up to 16), not billed tokens.
- Latency p50: stateful 6.4s / stateless 4.7s / generateContent 3.3s
  (3.5-flash-lite, small fixture).

## Deliverables (committed f5e10dae73, pushed to dispatch branch)

- `docs/ssot/jobs/devnest/2026-11-26-gemini4-interactions-text-agent-eval.yml`
- `reports/gemini-interactions-eval-2026-11-26.md` + 3 raw JSON artifacts
- `scripts/bench/gemini-interactions-eval.py` (g4 lanes wired for rerun)
- idc03 scratch: `/tmp/gemini-eval/{harness.py,results*.json,run*.log}`

## How to verify

- `python3 -m py_compile scripts/bench/gemini-interactions-eval.py`
- Report table vs `reports/gemini-interactions-eval-2026-11-26*.json`
- Re-run on idc03: `set -a; . ~/.config/secrets/gemini-keys.env; set +a;
  /tmp/gemini-eval-venv/bin/python /tmp/gemini-eval/harness.py out.json g4h_stateful`
  once a funded/gemini-4-entitled key exists.

## Follow-up

- gemini-4 eval is blocked on Tony's call: lift PAID monthly cap or provide a
  gemini-4-entitled key, then rerun the wired g4 lanes. No billing/key changes
  were made.

lessons:
- Interactions API needs api_version="v1beta" in google-genai 3.x or preview models 404.
- Stateless replay of function_call history requires thought-step signatures verbatim — dump response steps with model_dump(by_alias=True, exclude_none=True).
- usage.total_input_tokens reports context size, not request size — it grows identically in stateful and stateless modes.
- gemini-4 models are effectively paid-only: free tier gives hydrogen 20 req/day and neon/argon/carbon zero quota; check quota before designing evals around them.
- Literal-token grading undercounts ~2-7% on format variants ("4,200", "2:32 PM") — normalize before scoring recall checks.
