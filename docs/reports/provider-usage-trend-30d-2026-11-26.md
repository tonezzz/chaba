# Provider usage trend — 30 days ending 2026-11-26

Evidence artifact generated 2026-11-26 from live sources. Unit: **million tokens/day** (see caveats).

| Provider | 30d tokens (M) | Share of measured tokens |
|---|---:|---:|
| Devin (fleet, 556 sessions) | 2160.12 | 78.9% |
| OpenRouter (LiteLLM) | 293.7 | 10.7% |
| Gemini (LiteLLM) | 223.97 | 8.2% |
| Ada voice backends | 53.44 | 2.0% |
| Local Ollama (LiteLLM) | 6.64 | 0.2% |

LiteLLM spend across all models in window: **$75.82** (list-price compute, not invoiced).

## Daily series (M tokens)

| date | Devin | Gemini | OpenRouter | Ada voice | Ollama |
|---|---:|---:|---:|---:|---:|
| 2026-10-28 | 48.54 | 2.40 | 0.00 | 0.00 | 0.12 |
| 2026-10-29 | 15.37 | 0.05 | 0.10 | 0.00 | 0.07 |
| 2026-10-30 | 11.62 | 1.43 | 17.22 | 0.00 | 0.28 |
| 2026-10-31 | 11.04 | 1.75 | 0.00 | 0.00 | 1.66 |
| 2026-11-01 | 0.00 | 0.98 | 0.00 | 0.00 | 0.12 |
| 2026-11-02 | 0.00 | 3.36 | 0.93 | 4.24 | 0.11 |
| 2026-11-03 | 3.53 | 13.19 | 11.31 | 0.00 | 0.28 |
| 2026-11-04 | 0.00 | 0.16 | 19.60 | 0.00 | 0.07 |
| 2026-11-05 | 0.00 | 2.63 | 0.00 | 0.00 | 0.04 |
| 2026-11-06 | 15.35 | 2.98 | 0.30 | 0.00 | 0.07 |
| 2026-11-07 | 35.13 | 12.05 | 1.41 | 2.13 | 0.15 |
| 2026-11-08 | 42.89 | 4.45 | 0.00 | 5.39 | 0.09 |
| 2026-11-09 | 81.67 | 11.81 | 0.27 | 4.75 | 0.10 |
| 2026-11-10 | 0.00 | 0.00 | 0.00 | 3.37 | 0.10 |
| 2026-11-11 | 0.00 | 0.12 | 0.00 | 0.14 | 0.02 |
| 2026-11-12 | 3.22 | 3.41 | 0.00 | 0.26 | 0.07 |
| 2026-11-13 | 48.24 | 3.19 | 5.70 | 0.00 | 0.09 |
| 2026-11-14 | 51.00 | 0.00 | 19.32 | 0.16 | 0.20 |
| 2026-11-15 | 0.00 | 0.00 | 0.00 | 0.00 | 0.03 |
| 2026-11-16 | 13.27 | 1.05 | 0.00 | 2.06 | 0.04 |
| 2026-11-17 | 92.58 | 0.06 | 0.00 | 2.49 | 0.05 |
| 2026-11-18 | 146.15 | 1.94 | 0.00 | 0.00 | 0.05 |
| 2026-11-19 | 107.24 | 0.27 | 0.79 | 0.47 | 0.09 |
| 2026-11-20 | 88.02 | 5.64 | 2.07 | 0.00 | 0.04 |
| 2026-11-21 | 8.52 | 2.02 | 10.13 | 0.00 | 0.06 |
| 2026-11-22 | 0.00 | 0.01 | 0.00 | 0.00 | 0.03 |
| 2026-11-23 | 172.03 | 41.15 | 1.99 | 18.40 | 0.31 |
| 2026-11-24 | 672.90 | 24.27 | 70.47 | 2.81 | 0.22 |
| 2026-11-25 | 451.04 | 44.03 | 47.30 | 2.93 | 0.61 |
| 2026-11-26 | 40.77 | 39.57 | 84.79 | 3.84 | 1.47 |

## Sources and method

- **Devin:** `python3 scripts/devin/devin-usage.py --fleet --days 30 --json` over each runner's
  `~/.local/share/devin-dispatch/tasks/*/transcript.json` (`final_metrics.prompt + completion`).
  556 sessions; idc01 unreachable during scan.
- **LiteLLM / Ada:** `python3 scripts/litellm/usage-feed.py --days 30` on idc03 — `LiteLLM_SpendLogs`
  grouped by model prefix, plus `~/CascadeProjects/ada-voice/data/usage.jsonl` lanes.

## Caveats — read before comparing

- **Not the same accounting.** Devin's `total_prompt_tokens` is a cumulative per-step counter dominated
  by cached context (~97%); LiteLLM/Ada rows count API tokens. Treat this as a *burn-volume* trend, not
  a price comparison. Free-tier Devin (swe-2-high) is plan-allowance-bound, not invoiced; `devin /usage`
  is authoritative.
- 11-24 spike = 672.9 M Devin tokens across the fleet; 11-25 451 M. Both are dispatch bursts, not a
  single session. Runner timers were paused at the time, so these were supervised/manual dispatches.
- The reduction fix (PR #199) landed 11-24 for queue-time lane routing; this window predates most of
  its effect. Re-run the same command after a few weeks to measure change.
