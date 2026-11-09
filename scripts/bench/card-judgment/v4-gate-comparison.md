# v4 gate comparison — distilled brief vs raw snapshot

card: `card-distill-free-lane` (ADA-1133) — run 2026-11-09 on idc02
judge: `ada` entity, `gemini-3.5-flash-lite-free` via litellm gateway
(same model judged both input shapes; `--delay 2` — free-lane RPM
windows still produced 429 bursts, treated as infrastructure noise).

Corpus: `corpus.jsonl` rebuilt v3 first (94 cases; the on-disk file was
v2 and lacked the `open_requests`/`claim`/`action_status` gate fields —
v4 keeps exactly those raw). `corpus-v4.jsonl` = same cases, snapshot =
raw gate fields + fixed-slot distilled brief (distilled from the frozen
snapshot, not the live card — no proven_right leak).

## Headline

| run | corpus | action_accuracy | appropriate_deference | corr_precision | corr_recall | parse_fails |
|---|---|---|---|---|---|---|
| run15 | v3 raw | 0.5000 | 0.6170 | 0.9286 | 0.4333 | 14 |
| run16 | v4 distilled | 0.5213 | 0.6277 | 0.7778 | 0.4667 | 7 |
| **paired** | judged both runs, n=73 | **raw 0.5616 -> v4 0.5753** | raw 0.5753 -> v4 0.6575 | - | - | - |

**action_accuracy delta: +1.37pts paired / +2.13pts all-case — the
>2pts-drop kill criterion does NOT fire. Slots keep decisive signal.**

## What the slots changed

- v4 gained 7 cases raw missed — including the only `observe` case any
  run predicted correctly (observe-003) and four `act` cases.
  `needed_move_class` is doing real work.
- v4 lost 6 cases raw had — two of them `correct` where a checkable
  fact lived in comms prose the distiller compressed past
  (correct-025, correct-020, correct-002). The `evidence_present` slot
  is the lossy edge; it says *that* evidence exists, sometimes not
  *which*.
- `correction_precision` fell 0.93 -> 0.78: v4 predicts `correct` more
  often (recall up 0.43 -> 0.47). Slot briefs make the model *reach*
  for corrections; net accuracy is still up.

## Deterministic consumers

`rules` entity greps `brief`/`comms_tail` prose — stripped in v4:
accuracy 0.4149 raw -> 0.3617 v4 (-5.3pts). Expected and by design:
v4 snapshots are for LLM turns. Deterministic readers keep the raw
gate fields (still present) or the v3 corpus.

## Caveats

- Single judge: only flash-lite-free was a live free lane on idc02
  today (cf-70b: no CF_API_WORKER_TOKEN on host — gateway cf-llama-70b
  route broken; local ollama down; idc03 ollama wedged; OR-free over
  daily quota / or-gemma31b upstream key invalid). Judge = same model
  as the distiller for most cases — a cross-model check is the
  follow-up when a second free lane is healthy.
- 429 asymmetry (14 vs 7 parse-fails) is why the paired set is the
  headline number.
- Sample: 94 frozen decision moments; observe is thin (8 cases).

## Verdict

ADOPT for lane turns: fixed-slot distillation compresses the snapshot
~45% (mean 1269 -> 698 chars) with no accuracy loss. Keep v3 raw as
the corpus of record; v4 is the cheap turn-time view. Live consumer
wired: `verify_worker.py --with-distill` (off by default — flip when
the second-lane cross-check lands).
