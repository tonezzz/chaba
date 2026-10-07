# nest-01 — ops-event classifier (dense MLP, pure numpy)

First cell of the Chaba Nest curriculum. Task: predict `meta.type`
(13 classes) of Ada ops events from tool/hour/weekday/length features.
2000 real events from `ada-ha-events-tony` (MDDB), temporal 80/20 split.

## Result: 50.7% test accuracy (chance ~8%, majority baseline 61%)

Three real lessons in one run:

1. **Feature signal bounds everything.** Tool→type alone gives 81% by
   lookup — no architecture exceeds its features. The dense bet was
   correct (flat independent features), the ceiling was the data.
2. **Class imbalance collapses naive training.** Bare softmax+SGD
   converged to "always predict majority" (10% acc). Capped class
   weights (max 8×) fixed it — rare classes need amplified gradients
   but unbounded weights oscillate.
3. **Temporal split exposes drift.** Train window's dominant class
   isn't the test window's (jev_advisory wave hit the test period).
   Real ops data isn't IID — 61% baseline on test ≠ what train saw.
   Honest eval = time-ordered split, always.

## Artifacts

- `ops-events.jsonl` — pulled 2026-10-07 (`pull` inline, MDDB /v1/search)
- `train.py` — ~90 lines, numpy only. 10KB model.npz out.
- Run: `python3 train.py`

## Why this matters for Nest

A 10KB classifier that runs anywhere IS the node model shape. Next:
same pipeline, task where the temporal dimension carries the signal
(LSTM on sunsynk power history — nest-02).
