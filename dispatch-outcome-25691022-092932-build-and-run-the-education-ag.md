# dispatch-outcome — build+run the education-agent benchmark (card edu-agent-benchmark)

## What was built

- `scripts/bench-edu-manage.py` — three-lane benchmark harness modeled on
  `bench-hermes.py`. Reuses the real `lesson-miner.py` path (imported)
  for the `current` lane; an in-process OpenClaw-shaped tool-calling
  loop for the `clawbot` (openrouter/free) and `hermes` (omen ollama
  /v1 hermes3:8b) lanes; a `MockStore` standing in for the WP lesson
  CPT — no prod WP is ever touched. One fixed LLM judge
  (gemini-3.5-flash-lite via the LiteLLM gateway /v1beta — the direct
  free key is 429-saturated) grades all drafts on a 5-axis rubric.
  Supports `--lanes`, `--tasks`, `--limit`, `--reps`, `--no-judge`, and
  `--rescore` (recompute transcript metrics in a finished JSON after a
  corpus/scorer change without re-running lanes).
- `scripts/bench-edu-corpus.json` — fixed fixture corpus: 3 seeded
  lessons, 7 transcript tasks (golden keep/drop + create/update/hub
  action labels, `neutral_seed_topics` for convention-correct hub
  refreshes), 3 ops tasks (status/next_review/due-list), 3 recall tasks
  (incl. a correctly-report-none case). Day-offset dates keep it
  evergreen.
- `reports/bench-edu-manage-2026-10-22.{json,md}` — full results.
- `docs/ssot/jobs/models/2026-10-22-edu-agent-bench.yml` — SSOT entry.

## Result — verdict: current stays (AQ not met)

| lane | capture F1 | dedupe | sched/ops | recall | draft-Q | p50 | tokens-in |
|---|---|---|---|---|---|---|---|
| current | 1.0 | 3/5 | 5/5 | 3/3 | 5.0 | ~0-3s | 0.9k |
| clawbot | 1.0 | 4/5 | 5/5 | 3/3 | 4.72 | 12.5s | 74k |
| hermes | 0.545 | 2/5 | 3/5 | 1/3 | 3.9 | 19.4s | 31k |

clawbot **beat** current on dedupe (only lane to follow ada-nest-*
family naming + refresh the hub) and tied everything else, but did not
beat draft-quality (judge-is-current-model caveat documented), at ~80x
tokens and ~4x latency → AQ fails. hermes3:8b is unfit as manager agent
(search-then-give-up, missed re-ask and Thai transcript, filed
ephemeral content, one 659s timeout). All lanes $0.

Findings worth keeping: rephrased re-asks fork a second lesson in the
REAL pipeline (classify never sees the existing topic list — cheap fix:
feed topics into CLASSIFY_PROMPT); lesson-add's meta-overwrite resets
status->open and next_review->+7d on every re-file.

## Notes / deviations

- Real openclaw-gateway on tony-omen is loopback:18789 — unreachable
  over tailnet — so `clawbot` is the same agent surface in-process on
  the gateway's declared provider (`openrouter/free`).
- `hermes3:8b` had been GC'd from omen ollama since the T1 eval;
  re-pulled via /api/pull for this run.
- Verdict comm posted on card `edu-agent-benchmark` via board-api.

## Verify

```
python3 scripts/bench-edu-manage.py --lanes current --tasks t1-create-bbr-cubic --no-judge --out /tmp/b
cat reports/bench-edu-manage-2026-10-22.md
```
