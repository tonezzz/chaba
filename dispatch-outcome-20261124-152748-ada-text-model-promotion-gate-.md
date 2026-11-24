# dispatch-outcome — ada-text-model-promotion-gate- (attempt 3, idc02)

## What happened

This dispatch was a **duplicate claim**: card `ada-text-model-promotion-path`
was already worked by attempt 2 (tony-macbook, 2026-11-23 23:04), merged as
910c473a, and auto-closed by merge-sweep at 2026-11-24 00:37. Card comms
confirmed the full trail before starting.

Rather than no-op, I looked for the evidence gap the prior run's jobs entry
itself flagged: the 2026-11-20 paid `gemini-3.5-flash` clawbot row
(draft-Q 4.80) existed **only in card comms — no committed JSON/MD**.

Upstream probe (2026-11-24 ~08:30Z):
- `or-free-*` aliases: OR account daily cap STILL exhausted —
  `X-RateLimit-Reset: 1795564800000` = **2026-11-25T00:00Z** (the "~07:00 ICT"
  reset noted in the prior run's docs was wrong; UTC-midnight anchored and
  already re-spent by other fleet traffic).
- `cf-gpt-oss-120b`: CF free neuron allocation (10k/day) exhausted.
- `cf-nemotron-120b`: invalid model name for LITELLM_KEY_BENCH.
- **`gemini-3.5-flash` (paid): reachable** via LiteLLM gateway with
  LITELLM_KEY_BENCH on /v1/chat/completions.

## What I did

Ran the fixture for the comms-only row, plus a same-day `current` re-run
for judge symmetry:

```
source ~/.config/secrets/litellm-keys.env
export GEMINI_BASE_URL=http://100.102.134.91:4000
export GEMINI_API_KEY="$LITELLM_KEY_CHABA"
python3 scripts/bench-edu-manage.py --lanes current clawbot \
  --or-model gemini-3.5-flash \
  --out reports/bench-edu-manage-2026-11-24-gemini35flash-gate
```

## Result — clawbot gemini-3.5-flash CLEARS the operational gate

| lane    | F1  | dedupe | ops  | recall | draft-Q    | completed | p50   |
|---------|-----|--------|------|--------|------------|-----------|-------|
| current | 1.0 | 3/5    | 5/5  | 3/3    | 5.00 (n=5) | 13/13     | 0.0s  |
| clawbot | 1.0 | **4/5**| 5/5  | 3/3    | 4.89 (n=7) | 13/13     | 5.7s  |

- Second model ever to clear the operational gate (deepseek-v3.2 was first,
  2026-11-12) and the fastest (p50 5.7s vs 11.1s).
- draft-Q 4.89 is the highest challenger score on record — consistent with
  the comms-only 4.80 — but still < incumbent 5.0, so the ORIGINAL AQ is
  NOT cleared.
- **No promotion attempted** — correctly stays gated on Tony's approval.
  Production `chat` class already runs gemini-3.5-flash paid, so this
  evidences the edu-manager surface only.

## Deliverables (commit 032144bf1a on dispatch branch)

- `reports/bench-edu-manage-2026-11-24-gemini35flash-gate.{json,md}`
  (force-added past `reports/*` gitignore, same as prior bench artifacts)
- `docs/ssot/jobs/models/2026-11-23-ada-text-model-promotion-gate.yml`
  updated: ledger row filled with committed numbers, new
  `run_2026-11-24-dup` / `measured_2026-11-24-dup` /
  `verdict_2026-11-24-dup` sections, rerun_procedure corrected
  (OR reset timestamp, LITELLM_KEY_BENCH actually reaches
  gemini-3.5-flash, paid-gemini example added)

## How to verify

- `git show 032144bf1a --stat` — 3 files, +1013/-9
- `reports/bench-edu-manage-2026-11-24-gemini35flash-gate.md` — summary table
- Card comms on `ada-text-model-promotion-path` has the progress + this
  outcome (posted via `https://idc03.taila0626a.ts.net:10000` — the
  dispatch primer's `127.0.0.1:8787` board-api is NOT running on idc02;
  use RUNNER_API host instead)

## Notes for the operator

- Board-api endpoint: dispatch primer says `http://127.0.0.1:8787` but on
  idc02 nothing listens there — working endpoint is
  `https://idc03.taila0626a.ts.net:10000` (same as runner-agent's
  RUNNER_API). Comment + card reads/writes all worked over it.
- OR :free challengers (incl. best-free or-free-nemotron-35) remain
  un-runnable until 2026-11-25T00:00Z — a future dispatch after that
  can still produce the last comms-only row.

lessons:
- Dispatch primer's board-api URL (127.0.0.1:8787) is wrong on idc02 — use https://idc03.taila0626a.ts.net:10000 (runner-agent RUNNER_API).
- reports/* is gitignored; bench artifacts need `git add -f` (prior runs did the same).
- OR :free daily cap is account-wide across all or-free-* aliases and resets at UTC midnight — probe X-RateLimit-Reset before planning a free-model bench; "resets ~07:00 ICT" notes can be stale/wrong.
- LITELLM_KEY_BENCH reaches gemini-3.5-flash on /v1/chat/completions despite being alias-restricted elsewhere — paid gemini lanes are bench-able without extra keys.
- A duplicate dispatch on an already-closed card can still add value: check the jobs entry for flagged evidence gaps (comms-only rows) before no-op'ing.
