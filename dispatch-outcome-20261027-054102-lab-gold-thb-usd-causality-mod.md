# Dispatch outcome — lab-gold-thb-causality (first scored window)

## What was done

- Created `experiments/gold-thb-usd-causality/.venv` (gitignored) and installed
  pandas/numpy/statsmodels/scikit-learn; re-ran `analyze.py` end-to-end —
  reproduces 3,076 aligned observations 2014-11-07..2026-08-25 and the original
  Granger-causality findings (THB → XAU significant, reverse not).
- Wrote `experiments/gold-thb-usd-causality/score_window.py`: walk-forward
  directional-accuracy scorer for the lab metric (OOS accuracy > 60% over 30
  daily predictions). Two variants of the small THB→XAU causality rule:
  `threshold` (monthly Sharpe-searched threshold, same rule as
  `walkforward.py`) and `always` (threshold 0, predict every day). Outputs
  `data/predictions.csv` and `data/scored_window.json`.
- Recorded the trail in
  `docs/ssot/jobs/experiments/2026-10-27-gold-thb-usd-scored-window.yml`.
- Posted results + caveats to the card via board-api comment.

## Result

First scored window (last 30 scorable predictions, ending 2026-08-24 — the
last day whose next-day return exists):

- threshold model: **70.0% (21/30)**, window 2026-07-07..08-24 — meets >60%.
- always model: **66.7% (20/30)**, window 2026-07-13..08-24 — meets >60%.

Caveats for the 2026-11-01 review:

- Naive always-up baseline scored 63.3% / 66.7% on the same days; the model's
  edge over "predict up" is not significant (binomial p vs naive = 0.29 / 0.58).
- Over the full 2015–2026 OOS span, rolling-30 accuracy means are 58.2% / 56.2%
  and only ~35% of windows exceed 60% — the latest window is above average.
- **The card note "Data collection running" is stale**: the price CSVs were
  fetched once on 2026-08-26 via the Alpha Vantage MCP; no collector job, fetch
  script, or scheduled unit exists, and no API key is reachable from this
  worktree. Data is frozen at 2026-08-25 (~2 months old at review). If the lab
  continues, a real daily collector + scored-window append is the missing piece.

## How to verify

```bash
cd experiments/gold-thb-usd-causality
.venv/bin/python analyze.py        # regenerates data/aligned.csv, returns.csv, results.json
.venv/bin/python score_window.py   # regenerates data/predictions.csv, scored_window.json
cat data/scored_window.json        # window + OOS + rolling stats
```

## Files changed (committed on dispatch branch, not pushed)

- `experiments/gold-thb-usd-causality/score_window.py` (new)
- `experiments/gold-thb-usd-causality/data/scored_window.json` (new, force-added past `data/` ignore)
- `experiments/gold-thb-usd-causality/data/predictions.csv` (new, force-added)
- `docs/ssot/jobs/experiments/2026-10-27-gold-thb-usd-scored-window.yml` (new)
- `dispatch-outcome-20261027-054102-lab-gold-thb-usd-causality-mod.md` (this file)
