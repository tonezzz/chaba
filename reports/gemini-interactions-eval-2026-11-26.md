# Gemini Interactions API eval — stateful vs stateless vs generateContent

Date: 2026-11-26 · Card: `gemini4-interactions-text-agent-eval-2026-11-26` (ADA-1451)
Host: idc03 · Key: `GEMINI_API_KEY_MICHAEL` (free tier; value never printed)
SDK: `google-genai` 3.6.1 in `/tmp/gemini-eval-venv` · API: `v1beta` `/interactions`
Harness: `scripts/bench/gemini-interactions-eval.py` · Raw: `reports/evals/gemini-interactions-eval-2026-11-26{,-gen-rerun,-stateful}.json`

## Headline

**gemini-4 could not be evaluated on this key — quota, not code.**

| Model | Free-tier quota (MICHAEL key) | Observed |
|---|---|---|
| gemini-4-hydrogen | 20 req/day | 503 high-demand early, then 429 "20 requests per day… retry in 18h47m" — exhausted during probes |
| gemini-4-neon / -argon / -carbon | **0 tokens/min, 0 req/day on Free Tier** | instant 429 every call |
| gemini-4-* on GEMINI_API_KEY_PAID | paid project | still 429 "monthly spending cap" (verified 20:0x ICT) |

So the stateful-vs-stateless comparison ran on the newest free-tier models that
DO work: `gemini-3.5-flash-lite` and `gemini-3.1-flash-lite`. The Interactions
API mechanics measured here transfer directly to gemini-4 once quota exists.

## Fixture

Fixed 8-task set, each 2–3 user turns, deterministic fake tools
(get_weather, search_kb, calculator, get_stock, create_reminder, get_time).
Checks per turn: expected function calls (name + arg match) and answer tokens
(cross-turn recall of tool results and user-stated facts; one Thai turn).

Lanes:

- `*_int` — Interactions API, **stateless**: full step history resent every call
- `*_stateful` — Interactions API, `previous_interaction_id` chaining (new input only)
- `g35l_gen` — `models.generate_content` (current 3.x stateless text path)

## Results (adjusted scores — see grading note)

| Lane | Model / path | Tasks scored | Adjusted mean | Fatal calls | Notes |
|---|---|---|---|---|---|
| g35l_stateful | 3.5-flash-lite / Interactions stateful | 8/8 | **1.000** | 0 | perfect incl. cross-turn recall |
| g35l_int | 3.5-flash-lite / Interactions stateless | 8/8 | **1.000** | 0 | perfect |
| g31l_stateful | 3.1-flash-lite / Interactions stateful | 8/8 | 0.975 | 0 | t2 paraphrased "flock" away (0.8) |
| g31l_int | 3.1-flash-lite / Interactions stateless | 8/8 | 1.000 | 0 | t4 answered "2:32 PM" not "14:32" (format-only) |
| g35l_gen | 3.5-flash-lite / generateContent | 4/8 completed | 1.000 where run | 429 quota | free-tier quota died mid-run; rerun got t1–t4 perfect then 429 again |

Raw literal-token scores were lower (0.93–1.0); all diffs were format-only
("4,200" vs "4200", "2:32 PM" vs "14:32") or one genuine paraphrase miss.
Adjusted = comma-normalized + 12h↔24h time equivalence.

## Mechanics measured

- **Request size:** stateful sends 1–2 input steps per call; stateless resends
  the whole transcript (up to 16 steps by late turns).
- **Billed/context tokens:** `usage.total_input_tokens` grows with conversation
  length in BOTH modes (med ~405 → max ~620) — the server counts full context
  either way, so stateful saves request bytes/latency surface, not context tokens.
- **Latency p50:** stateful 6.4s vs stateless 4.7s (3.5-flash-lite);
  generateContent 3.3s. Small fixture — stateful's per-call overhead is
  server-side state resolution; expect it to amortize on longer sessions.
- **Thought signatures:** replaying function_call history REQUIRES the
  `signature` field on thought steps (Gemini 3 rule). Resending stripped
  steps → 400 "Function call is missing a thought_signature". The harness
  dumps response steps verbatim (`model_dump(by_alias=True)`) — works.
- **Tool loop:** `status: requires_action` + `function_call` steps → send
  `function_result` steps (`call_id`, `name`, `result` string) as the next
  input; chain `previous_interaction_id` to the latest interaction id.
- **API version:** SDK defaults to v1 — `interactions.create` needs
  `api_version="v1beta"` or preview models 404.

## Verdict

Interactions API is production-usable on 3.x: perfect scores on both
stateful and stateless paths, clean tool-call loop, and stateful chaining
works exactly as documented. **gemini-4 evaluation is blocked on quota** —
needs either the paid project's spend cap lifted (Tony decision, unchanged)
or a free-tier key on a project with gemini-4 access. Recommend re-running
this harness (`scripts/bench/gemini-interactions-eval.py`) once a funded
key exists; lanes `g4h_stateful/g4h_stateless/g4n_stateful` are already wired.
