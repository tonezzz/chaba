# Dispatch outcome — jevteam-omen-or-lane-admission

Define and benchmark Omen and OpenRouter as separate JevTeam lanes; add
live preflight, matched held-out benchmark vs KK-Mac/OpenCode/Devin,
normalized decision envelope; keep auto-routing OFF until gates pass.

## What changed

- `docs/ssot/infrastructure/ssot.devnest-lanes.yml` — two new lanes,
  both `status: admission-pending` (no automatic routing):
  - `omen` (plane: decision, executor: NONE) — four endpoints on
    tony-omen tailnet 100.75.102.88 (:8777 gemma-3-4b heavy scorer,
    :8778/:8779 gemma-3-1b students, :8780 distilmulti confirm-gate
    only). task_classes: lane-classify assist, noul pre-gates,
    scoring/audit-replay, privacy-sensitive async. must_not: execute
    mutations, replace keyword classifier without bench proof, serve
    interactive latency.
  - `openrouter` (plane: work) — LiteLLM gateway
    http://100.102.134.91:4000 only; free tier (or-free-*, quota-shaped
    ~1000 req/day fleet-wide) and paid tier (or-deepseek-v4-flash,
    cost-ledgered). Controls: per-key max_budget, envelope max_tokens,
    401/402/429/timeout fallback ladder, SpendLogs ledger, no secrets.
  - `open_gaps` + `references` updated; `ssot.model-routing.yml`
    t2-openrouter-free cross-referenced.
- `schemas/jevteam-decision-envelope.schema.json` +
  `scripts/jev/decision_envelope.py` — normalized decision envelope
  (executor/provider/model/lane/task_class/artifact/expect/max_tokens/
  cost_budget/fallback) as draft-2020-12 schema + stdlib validator
  (lint/normalize/selftest; selftest 7/7 PASS). Refuses decision-plane
  mutations on omen and paid-model/zero-budget mismatches.
- `scripts/jev/lane-preflight.py` — read-only live admission probe:
  health/metrics/key-info + one bounded smoke call; fail-closed
  eligible/degraded/down verdicts, exit 0/1/2.
- `scripts/jev/lane-arena.py` — matched held-out benchmark: decision-
  arena v2 corpus (50 labeled cases: confirm/tool/pipe/stag) through
  every arm — native /v1/systemone for omen :8777-:8780 + jevos
  idc02:8777, OpenAI-compat chat arms for kk-mac qwen3:8b,
  litellm/gemini-3.5-flash-lite, or-free-nemotron-35,
  or-deepseek-v4-flash, plus a literal `opencode run` executor arm.
- `docs/ssot/jobs/devnest/2026-11-24-omen-openrouter-jevteam-lanes.yml`
  — job trail with method/measured/verdict/followups.
- `evals/results/jev/lane-arena-*-20261124.{json,md}` — benchmark
  artifacts.

## Results (matched 50-case held-out corpus, 2026-11-24)

| arm | acc | n | p50 | notes |
|---|---|---|---|---|
| oc-executor (real `opencode run`) | 0.90 | 50 | 5.7s | best arm |
| oc-free-flashlite (chat path) | 0.86 | 50 | 0.8s | same brain, no agent loop |
| or-paid-deepseek (LiteLLM paid) | 0.86 | 50 | 1.2s | cost-ledgered |
| kkmac-qwen38b | 0.80 | 50 | 21.7s | strong acc, slow |
| omen-8780 | 0.48 | 50 | 0.1s | confirm 1.00 / tool 0.06 — domain lock |
| omen-8778 / 8779 students | 0.40 | 50 | 5.8-21.5s | weak across families |
| jevos-idc02 (incumbent) | 0.38 | 50 | 122s | 11 errors, all stag timeouts |
| omen-8777 (w=3, full) | 0.04 | 50 | 180s | 47/50 timeouts — CPU-bound |
| omen-8777 (w=1, confirm×12) | 0.25 | 12 | 74s | sequential: 3/12, 4 timeouts, miscalibrated |
| or-free-nemotron | SKIP | — | — | OR :free 429 daily cap |

Preflight: omen ELIGIBLE (all 4 endpoints /health 200 + smoke answered;
8780 noul=0.006 confirms confirm-gate domain lock). openrouter DEGRADED
(gateway healthy, BENCH key $1.83/$4 headroom, but OR :free leg 429 —
correctly refuses admission).

Key finding: every chat/executor arm (0.80-0.90) beats every omen arm —
but the incumbent jevos baseline (0.38, degraded under load) is worse
than the omen students. The whole local decision plane is below the
chat-tier floor today. Omen's viable scope is exactly the carded one:
confirm-gate (8780 = 1.00 on confirm), privacy-sensitive scoring,
audit/replay — never interactive, never mutations. Devin is non-viable
as a corpus arm (agent executor, not a completion endpoint);
oc-executor is the literal substitute.

omen-8777 deep-dive: even at workers=1 the confirm family (its home
domain) scored 0.25 with p50 74s/call and 4/12 timeouts — the earlier
smoke noul=0.990 was one easy prompt and did not generalize. Under
ANY concurrency (w=2 or w=3) every call exceeds the 180s timeout.
8777 is a serial-only, ~1-2min/call, poorly-calibrated scorer —
batch/audit at best, never a routing lane.

## Gates status

Automatic production routing stays OFF for both lanes — matches the
card gate. Promotion path (in job doc followups): flip
admission-pending -> live per task_class only when preflight green +
lane-arena beats jevos per-family + cost gate recorded.

## How to verify

- `python3 scripts/jev/decision_envelope.py selftest` — 7/7 PASS
- `python3 scripts/jev/lane-preflight.py --lane omen` / `--lane openrouter`
- `python3 scripts/jev/lane-arena.py --arms <subset> --workers N`
- `python3 -c "import yaml; yaml.safe_load(open('docs/ssot/infrastructure/ssot.devnest-lanes.yml'))"`
- Benchmark artifacts: `evals/results/jev/lane-arena-*-20261124.md`

lessons:
- LiteLLM per-key model allowlists differ (BENCH 19 vs CHABA 44 models) — a bare model id can 403 on one key while working on another; check `/key/info` or `models` first.
- OR `:free` aliases share a ~1000 req/day account cap — fleet traffic exhausts it; expect 429 and treat free tier as bursty-only.
- CPU-bound local scorers (omen 8777 4B) collapse under benchmark concurrency — timeouts, not wrong answers; run workers=1 for true accuracy.
- jevos incumbent baseline degraded live (11/50 timeouts, 122s p50) — benchmark baselines must be re-measured, not assumed.
- `opencode run` needs `LITELLM_KEY` env with a key whose allowlist includes the model; CHABA key worked where BENCH failed.
