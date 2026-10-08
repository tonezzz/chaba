# nest-02 — sunsynk LSTM (pure numpy, gates visible)

Task: last 24h of [PV, load, battery-SOC, grid] hourly → next-hour PV
power. Data: 45 days / 1079 hourly means from michael-ha Solis inverter
via `recorder/statistics_during_period` websocket.

## Result: LSTM 1498W RMSE — seasonal-naive BEATS it (1411W)

```
test RMSE:  LSTM 1498W | yesterday-same-hour 1411W | persistence 1451W
train mse:  0.154 → 0.017 (converged; not underfit)
weights:    21.9KB — still nest-node scale
```

## Lessons — richer than nest-01's

1. **A converged model can still lose.** Loss fell 9× but the naive
   baseline won. Solar is periodic by *astronomy*, not statistics —
   "same hour yesterday" already encodes earth's rotation. The LSTM
   had to learn what the baseline is told.
2. **Half the task is trivial.** 47% of hours are night-zero PV;
   errors concentrate in cloud-transient daytime. Aggregated RMSE
   hides that the model is fighting on a knife-edge subset.
3. **Feature engineering is the next lever.** Feeding hour-of-day
   (or sun elevation) explicitly would hand the model what it
   struggled to infer — next increment, not more epochs.
4. **BPTT is the conveyor's price.** ~50 lines of careful backward
   pass vs 4 lines for nest-01's softmax. Recurrence buys memory;
   costs gradient plumbing.

## Why LSTM exists (the bet)

Order matters AND long gaps matter. Vanilla RNN forgets — gradients
vanish over long chains. LSTM's fix is the **cell conveyor**: `c` flows
through `f*c + i*g` — an additive path where gradients don't decay.
Gates (sigmoid → 0..1 multipliers) decide what to forget/accept/expose.
On this data the memory paid for cloud-gap persistence.

## Artifacts

- `sunsynk-hourly.json` — raw ws pull (45d, 4 channels)
- `train.py` — visible gates + BPTT, numpy only
- `model-lstm.npz` — 21.9KB

## Next cell

nest-03: transformer (self-attention) on the SAME series — attention
vs recurrence on identical data is the comparison that teaches why
transformers displaced LSTMs (parallel training, no fixed bottleneck,
but O(n²) and no built-in recency).
