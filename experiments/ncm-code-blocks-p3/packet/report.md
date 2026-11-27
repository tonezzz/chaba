# NCM Variant B — P3 shadow report

- card: `ncm-variant-b-p3-shadow` (parent OPS-1325)
- corpus: `ncm-variant-b-p3-shadow-v1` — 30 corpus tasks + 3 fresh packs x 3 paired reps = 99 cells/arm
- providers: choice `idc03:http://127.0.0.1:8017/v1/systemone (jevos-v5)`; glue `tony-dell qwen2.5:7b-instruct digest 845dbda0ea48`
- pre-registered gate: median advantage >= 0.1, guard <= 0, >= 1 fresh pack(s)

| rep | seed | lane pass | glue pass | advantage | guard |
|---|---|---|---|---|---|
| 0 | 42 | 0.5758 | 0.1212 | +0.4545 | 0 |
| 1 | 7 | 0.5758 | 0.0909 | +0.4848 | 0 |
| 2 | 13 | 0.5758 | 0.0909 | +0.4848 | 0 |

- **median advantage: +0.4848** (gate 0.1)
- **total guard violations: 0**
- fresh packs: ['kk-mac-mlx-colab-scene0-control-20261124', 'kk-mac-mlx-colab-scene1-20261124', 'kk-mac-mlx-vimax-goldenhour-s0-20261124'] — lane pass 0/9, glue pass 0/9; self-token F1 lane 0.4348 vs glue 0.3333

## Pass rate by chosen block role

| block | n | lane pass | glue pass |
|---|---|---|---|
| assemble | 3 | 1.0 | 0.3333 |
| bench | 9 | 1.0 | 1.0 |
| delivery | 3 | 1.0 | 0.0 |
| i2v | 18 | 1.0 | 0.0 |
| misc | 18 | 0.0 | 0.0 |
| model-slot | 3 | 1.0 | 0.0 |
| preview | 6 | 1.0 | 0.0 |
| probe | 12 | 0.0 | 0.0 |
| render | 12 | 0.0 | 0.0 |
| shadow | 6 | 1.0 | 0.0 |
| subs | 3 | 1.0 | 0.0 |
| tts | 3 | 1.0 | 0.0 |
| vo | 3 | 1.0 | 0.0 |

## Verdict: **PROMOTE**

Shadow only — no production lane switch, no user-facing promotion. Replay proof: `packet/replay-proof.json` (0 provider calls).
