# info-find efficiency benchmark

Decision support for one question: **when does loading `info-find` beat bounded direct `grep`/`read` retrieval?**

## Design

- 8 tasks from the 2026-11-24/25 session history: 4 narrow (targeted fact) and 4 cross-source (SSOT + code + KB/MDDB).
- Arm A: `python3 scripts/devnest/info_find.py run --query ... --offline --max-results 5` — planner + local sources (SSOT, code, MDDB) with per-session cache/audit.
- Arm B: 1–2 bounded `grep ... | head` commands chosen to answer the same fact.
- Both arms are offline, read-only, and use the same worktree/model-free tools. No live writes, no agent-tool sources.
- Metrics: `tokens_est` (bytes/4), wall-clock ms, tool-call count, and correctness against `required_facts` in `tasks.json`.

## Decision rule (set before running)

- Cross-source: adopt/enforce `info-find` only if median Arm-A tokens ≤ 70% of Arm-B **and** correctness is equal or better.
- Narrow: keep direct tools if Arm-B tokens are lower with equal correctness.
- Otherwise leave `info-find` optional and document the trigger boundary.

## Run

```bash
python3 evals/info-find-efficiency/run.py
python3 -m pytest tests/test_info_find_benchmark.py -q
```

Outputs: `results.json` (per-task evidence) and `report.md` (table, medians, decision).

## Caveats

Tool-level only — it does not measure the model's decision overhead or answer quality beyond required-fact presence. Eight tasks and a rough token proxy make this **directional evidence**, not a conclusive study. The agent-level A/B (skill-creator style, with/without skill) remains future work if model rate limits allow.

Observed result: with the default offline plan, `info-find` returned generic ranked excerpts and missed the required facts on all 8 tasks, at roughly 18x the tokens and 20x the wall time of bounded grep; hydrating top local paths did not change that. This supports keeping direct tools for narrow lookups and not enforcing `info-find` for cross-source work without a better query/routing strategy.
