# Short-command recognizer — stdlib prototype

Tiered recognizer for short commands ("status", "play", "turn off the
AC", "explain OPS-0912", Thai equivalents). Research doc:
`docs/kb/short-command-recognition-research.md`.

## Run

```bash
python3 eval/run_eval.py              # corpus eval — wrong-fire gate + deflection
python3 eval/run_eval.py --json       # machine-readable rows
python3 eval/run_eval.py --sweep      # T1 accept-threshold frontier (OPS-0919)
python3 eval/run_eval.py --accept 0.45 --gray 0.30 --margin 0.06
python3 recognizer.py                 # stdin -> per-line tier/intent JSON
```

No dependencies beyond stdlib — runs on any host, any Python 3.9+.

## Tiers

| tier | what | cost | implemented |
|---|---|---|---|
| T0 | exact phrase table + anchored, operand-gated regex | ~µs | yes |
| T1 | char n-gram TF-IDF cosine vs intent prototypes; accept/gray/reject zones + margin gate + operand gates + vetoes | ~ms | yes |
| T2 | local small-LLM route+entity (ada-voice `command_lane` -> `/v1/systemone`) | ~s | declared, not in proto |
| T3 | pass-through to full pipeline (provider turn) | — | n/a |

The recognizer only ever CLAIMS below T3 when a gate clears; everything
else escalates (gray-zone items keep their candidate for T2). Wrong
local action >> slow provider turn, so gates are precision-first.

## Corpus conventions (`corpus.jsonl`)

- `"<intent>"` — hard command, must be claimed at T0/T1
- `"t2:<intent>"` — real command beyond T0/T1 reach; claim-with-intent
  or escalate are both correct (escalation is T2's job)
- `"pass"` — non-command; ANY claim is a wrong-fire

Current result: 68 items, **0 wrong-fires**, 90.2% deflection
(T0=39, T1=7 claims; 5 soft commands correctly escalate to T2).
`--sweep` shows the accept-threshold frontier: ≥0.38 is the lowest
zero-wrong-fire operating point on this corpus (default 0.42).
