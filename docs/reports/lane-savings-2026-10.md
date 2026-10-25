# Lane savings report — 2026-10

Generated 2026-10-25T12:28:33+00:00 by `scripts/board/lane-savings.py`. Catalog: `docs/ssot/infrastructure/ssot.devnest-lanes.yml`.

**Policy:** savings are claimed only for completed runs with usage evidence; counts otherwise; no dollar figure is emitted without measured tokens/cost.

## Lane usage this month (board action evidence)

| lane | cards | done | verified | token-evidenced | tokens (in/out) |
|---|---|---|---|---|---|
| deterministic | 5 | 5 | 0 | 0 | 0/0 |
| devin | 420 | 418 | 238 | 0 | 0/0 |
| free-opencode | 1 | 1 | 0 | 1 | 2050/305 |
| manual | 37 | 25 | 0 | 0 | 0/0 |

Dispatch-outcome files merged for 2026-10: **220** (devin-lane session stream).

## Pack/bench artifacts (measured cheap-lane tokens)

| artifact | lane | tasks | tokens in | tokens out | cost_usd | p50 |
|---|---|---|---|---|---|---|
| reports/bench-edu-manage-2026-10-23-colab-t4-store-aware.json | local-gpt-oss-20b | 13/13 | 33905 | 7384 | 0.0 | 21.5 |
| reports/bench-edu-manage-2026-10-24-clawbot-store-aware-reps3.json | clawbot | 13/13 | 57002 | 10229 | 0.0 | 12.9 |
| reports/bench-edu-manage-2026-10-24-clawbot-store-aware-reps3.json | clawbot | 13/13 | 55922 | 7278 | 0.0 | 15.5 |
| reports/bench-edu-manage-2026-10-24-clawbot-store-aware-reps3.json | clawbot | 13/13 | 63405 | 8973 | 0.0 | 14.2 |
| reports/bench-edu-manage-2026-10-22.json | current | 13/13 | 890 | 211 | 0.0 | 0.0 |
| reports/bench-edu-manage-2026-10-22.json | clawbot | 13/13 | 74275 | 9350 | 0.0 | 12.5 |
| reports/bench-edu-manage-2026-10-22.json | hermes | 12/13 | 31126 | 3320 | 0.0 | 19.4 |
| reports/bench-edu-manage-2026-10-24-colab-t4-store-aware-http500.json | local-gpt-oss-20b | 12/13 | 36414 | 6162 | 0.0 | 16.1 |
| reports/bench-edu-manage-2026-10-24-clawbot-baseline-reps3.json | clawbot | 13/13 | 59623 | 8725 | 0.0 | 11.9 |
| reports/bench-edu-manage-2026-10-24-clawbot-baseline-reps3.json | clawbot | 12/13 | 77998 | 10757 | 0.0 | 11.8 |
| reports/bench-edu-manage-2026-10-24-clawbot-baseline-reps3.json | clawbot | 13/13 | 51548 | 7793 | 0.0 | 8.4 |
| reports/bench-edu-manage-2026-10-24-nemotron-supervl-baseline-reps3.json | clawbot | 12/13 | 69329 | 8431 | 0.0 | 9.7 |
| reports/bench-edu-manage-2026-10-24-nemotron-supervl-baseline-reps3.json | clawbot | 11/13 | 60712 | 7829 | 0.0 | 12.5 |
| reports/bench-edu-manage-2026-10-24-nemotron-supervl-baseline-reps3.json | clawbot | 13/13 | 65021 | 8823 | 0.0 | 9.4 |
| reports/bench-edu-manage-2026-10-24-nemotron-supervl-rate-limit-probe.json | clawbot | 0/2 | 0 | 0 | 0.0 | 31.1 |
| reports/bench-edu-manage-2026-10-23-turn3-store-aware.json | local-gpt-oss-20b | 13/13 | 36178 | 7327 | 0.0 | 81.6 |
| reports/bench-edu-manage-2026-10-23-colab-t4.json | local-gpt-oss-20b | 13/13 | 41472 | 6921 | 0.0 | 14.7 |
| reports/bench-edu-manage-2026-10-23.json | local-gpt-oss-20b | 13/13 | 43305 | 6191 | 0.0 | 78.3 |

Measured pack tokens: **983,829** (cost_usd 0.0).

## Offloaded sessions (cheap lanes, evidence-bound)

- `eval-o1-opencode` lane=deterministic runner=idc02 evidence=action.result,comms
- `eval-surface-probe` lane=deterministic runner=idc02 evidence=action.result,comms
- `report-session-loop` lane=deterministic runner=tony-dell evidence=action.result,comms
- `runner-agent-smoke` lane=deterministic runner=idc02 evidence=action.result,comms
- `runner-script-smoke` lane=deterministic runner=idc01 evidence=action.result,comms
- `jev-opencode-free-probe` lane=free-opencode runner=idc02 evidence=action.result,tokens,comms

## Honest bottom line

6 cheap-lane session(s) with usage evidence (2,355 measured cheap-lane tokens) + 18 measured pack run(s). A dollar figure requires a measured paid-arm comparison — see job docs for per-task reference rates; do not extrapolate unmeasured sessions.
