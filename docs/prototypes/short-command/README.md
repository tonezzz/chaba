# Short command recognizer — prototype

Host-agnostic reference implementation of the tiered short-command
recognizer described in
`docs/kb/short-command-recognition-research.md` (card
`devin-research-short-command-recognition-d948ed` / DEV-0484).

Pure stdlib Python (3.8+). No models, no network, no GPU — T0+T1 run
anywhere. T2 activates only when `SCR_ROUTER_URL` is set.

## Tiers

| tier | what | cost | fires when |
|---|---|---|---|
| T0 | template/grammar match (hassil-lite syntax) | ~0.1 ms | exact-ish grammar hit, slots extracted |
| T1 | exemplar similarity | ~1 ms | score ≥ 0.40 accept; 0.25–0.40 "gray" (did-you-mean) |
| T2 | local router LLM | seconds | `SCR_ROUTER_URL` set + schema-valid reply |
| — | no_match | — | caller escalates to the normal provider turn |

Template syntax (hassil-style): `(a|b)` alternation, `[x]` optional,
`{slot}` placeholder. Whitespace compiles to `\s*` so unspaced Thai
matches. Slot kinds: `list` (canonical → aliases), `regex` (patterns),
`rest` (capture remainder).

## Run

```sh
python3 recognize.py "turn on the kitchen light"
# {"status":"match","intent":"HassTurnOn","slots":{"name":"kitchen light"},"tier":"T0",...}

python3 recognize.py "กี่โมงแล้ว"          # Thai works
python3 recognize.py "explain 0905"        # board commands
python3 recognize.py --trace "แก้ไขด้วย"    # shows which tier fired
cat eval/corpus.jsonl | python3 -c '...'   # or pipe via --stdin
```

## Eval

```sh
python3 eval/run_eval.py          # per-tier accuracy/deflection/wrong-fire
python3 eval/run_eval.py --sweep  # T1 threshold sweep
python3 eval/run_eval.py --corpus eval/corpus-tg-qwen.jsonl   # real TG voice (qwen3 hyps)
python3 eval/run_eval.py --corpus eval/corpus-tg-ref.jsonl    # real TG voice (Gemini refs)
```

Current corpus (51 items, EN/TH/code-switch/negatives): 100% correct,
0 wrong-fires, 88% deflection — T0 resolved 38, T1 resolved 7
(paraphrases like "turn the heater on" vs exemplar "turn on the
heater", score 0.87). This is a synthetic floor: calibrate against the
real TG voice corpus before trusting thresholds (research question 1
in the doc).

## Grammar

`commands.json` carries the starter spec — intents for the command
classes already in-system: HassTurnOn/Off/LightSet (EN+TH),
GetTime/GetDate, BoardExplain/Approve/Reject, MemoryCorrect (EN+TH),
ControlStop, Greeting/Thanks deflections. Surfaces bind subsets:
voice gets the Hass* + MemoryCorrect classes, TG relay gets all,
DevNest keeps its approve-gate on top.

## Optional scorers

- `SCR_EMBED_URL` — POST `{"text": "..."}` → `{"embedding": [...]}`;
  T1 switches from lexical to cosine-over-embeddings, with automatic
  fallback to lexical on endpoint failure.
- `SCR_ROUTER_URL` — POST `{"text": "..."}` → `{"intent","slots"}`;
  T2 validates intent against the known set (unknown intents are
  dropped) and is silent on timeout — the circuit-breaker behavior
  OPS-0605 taught us.
