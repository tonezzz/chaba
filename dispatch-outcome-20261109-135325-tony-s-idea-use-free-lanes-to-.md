# Dispatch outcome — card-distill-free-lane (ADA-1133)

**Result: done — all four deliverables shipped, quality gate PASSED
(adopt distilled briefs).**

## What changed (commit 15d2c7ed0 on dispatch branch, not pushed)

- `scripts/bench/card-judgment/distill.py` — rewritten: fixed 7-slot
  template {state, open_asks, gates, evidence_present, staleness,
  last_action, needed_move_class}; lane chain cf-70b -> local-ollama ->
  or-free -> flash-lite-free -> gemini-direct (verify_worker pattern,
  each leg env-overridable, dead legs skipped); sidecar cache
  `~/.cache/card-distill/<id>.json` keyed by (card_id, updated) for
  live cards or snap:<content-hash> for frozen bench snapshots;
  lane=none failures never cached. Module API: `distill_card`,
  `pseudo_card`, `snapshot_key`, `brief_text`.
- `schemas/card-distill-slots.schema.json` — the slot contract
  (enums on staleness + needed_move_class), jsonschema-verified.
- `scripts/bench/card-judgment/build_corpus_v4.py` — v4 corpus
  builder; distills the frozen case snapshot via pseudo_card (no
  proven_right leak), keeps the decisive gate fields RAW
  (title/priority/review_kind/tags/spec_present/open_requests/claim/
  action_status), adds `--retries/--retry-wait` for RPM windows.
- `scripts/bench/card-judgment/corpus.jsonl` — rebuilt v3 first:
  on-disk file was v2 and lacked the gate fields; 843 done cards ->
  94 cases now carrying open_requests/claim/action_status.
- `corpus-v4.jsonl` — 94/94 distilled via flash-lite-free, 0 fails;
  snapshot mean 1269 -> 698 chars (-45%).
- `scripts/ada-jobs/verify_worker.py` — `--with-distill` flag attaches
  the slot brief to Ada's live turn (second consumer; off by default).
- `score.py` — new `--delay` flag (per-case sleep; 429 bursts on free
  lanes otherwise show up as parse-fail and contaminate metrics).
- `tests/test_card_distill.py` — 8 offline tests (normalize, schema,
  pseudo_card, cache keying, failure-not-cached, chain order): green.
- Bench artifacts: `run15-flashlite-v3raw.{md,json}`,
  `run16-flashlite-v4distilled.{md,json}`, `v4-gate-comparison.md`.
- Trail: `docs/ssot/jobs/bench/2026-11-09-card-distill-v4-gate.yml`.

## The bench comparison (the gate)

Judge: `ada` entity, `gemini-3.5-flash-lite-free` via litellm gateway,
`--delay 2`, 94 cases each.

| | raw v3 | v4 distilled |
|---|---|---|
| action_accuracy (all 94) | 0.5000 | **0.5213** |
| action_accuracy (paired n=73, both judged) | 0.5616 | **0.5753** |
| appropriate_deference (paired) | 0.5753 | 0.6575 |
| correction_precision | 0.9286 | 0.7778 |
| parse_failures (429 noise) | 14 | 7 |

**Delta +1.37pts paired — the >2pts-drop kill criterion does not fire;
slots keep decisive signal.** v4 even gained the only observe case any
run got right (needed_move_class works). Lost edge: 2-3 `correct`
cases where the checkable fact lived in prose — `evidence_present` is
the lossy slot. Rules entity on v4 drops -5.3pts (prose stripped by
design — deterministic consumers keep v3/raw gate fields).

## Caveats

- Single judge lane today: cf-70b has no worker token on idc02,
  local+idc03 ollama dead/wedged, OR-free over daily quota + bad
  upstream key. Judge == distiller model for most cases — cross-model
  check is the listed follow-up.
- verify_worker `--with-distill` is wired but off by default — flip
  after the cross-check.

## How to verify

```
python3 tests/test_card_distill.py                       # 8 tests
python3 scripts/bench/card-judgment/distill.py --json <card_id>   # live
python3 scripts/bench/card-judgment/build_corpus_v4.py --limit 3  # rebuild
# A/B: score.py --entity ada --model gemini-3.5-flash-lite-free \
#   --base-url http://100.102.134.91:4000/v1 --api-key-env LITELLM_KEY_CHABA \
#   --corpus corpus.jsonl | corpus-v4.jsonl
cat scripts/bench/card-judgment/v4-gate-comparison.md
```
