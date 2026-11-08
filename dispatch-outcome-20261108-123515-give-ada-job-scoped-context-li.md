# Dispatch outcome — ada-job-brief-builder (2026-11-08, idc02)

## What changed (commit fe405f258 on dispatch branch, not pushed)

- **`scripts/ada-jobs/brief_builder.py`** (new) — card → job-scoped
  context bundle assembled before her turn:
  - related SSOT: mddb vector-search on the content plane
    (`ADA_BRIEF_MDDB_URL`, default `http://idc03.taila0626a.ts.net:11027/v1`,
    collection `infrastructure-ssot`) + local `docs/ssot` keyword grep
    as offline path (`--offline`, auto-fallback on mddb failure)
  - KB lessons: same search over `chaba-lessons` +
    `kb-{development,features,operations,system}` — pointers, not hydrated docs
  - top-3 similar done-cards: pure-stdlib TF-IDF nearest neighbors over
    `scripts/bench/card-judgment/corpus.jsonl`, returned with
    `category` + `decision_point` + `proven_right`. Self excluded by card_id.
  - `render()` emits a bounded `=== JOB BRIEF ===` block; CLI supports
    `--card <id>` (board-api fetch), `--card-file`, `--json`,
    `--corpus-briefs` (per-case bench briefs).
- **`scripts/ada-jobs/verify_worker.py`** — `--with-brief` flag: builds
  + prints the bundle before the decision turn, injects as
  `snap.job_brief` (both verify and `--sweep cleanup` prompts). Brief
  failure degrades to no-brief, never blocks the turn.
- **`scripts/bench/card-judgment/score.py`** — `--briefs <json>` injects
  per-case `job_brief` (leave-one-out: the case's own card is excluded
  from neighbors AND `infrastructure-ssot` hits so its own comms/outcome
  can't leak the gold label).
- **`scripts/bench/card-judgment/briefs.json`** — 98 leave-one-out briefs.
- **`docs/ssot/infrastructure/ssot.jobs.yml`** — ada-jobs-verify note
  documents the flag (opt-in pending flip decision).
- **`docs/ssot/jobs/ada/2026-11-08-ada-job-brief-builder.yml`** — jobs
  trail with design + measured numbers.

## Done-condition evidence

1. **`verify_worker --with-brief` scores a real card, bundle shown:**
   probe card `ada-verify-probe-job-brief` created via board-api
   (review/verify, tag ada-verify). Run (litellm `chat`): brief printed —
   its top-2 neighbors were the sibling probe cards
   `ada-verify-probe-{board-api,litellm}-alive` with their proven-right
   observe outcomes — she then **closed** review→done citing the real
   probe (`GET /cards` HTTP 200). Card ADA-1179 closed on the board.
2. **Bench delta on the defer boundary measured** (98 cases, entity ada,
   temp 0, litellm :4000):
   - `gemini-3.5-flash-lite` (weak boundary): acc 0.49→0.61 (+12pt),
     deference 0.51→0.61 (+10pt), correction_precision 0.88→1.0.
     Fact-case over-deferral 47→38 AND defer-gold recall 29/30→30/30 —
     both directions of the boundary improve.
   - `chat` (calibrated): deference 0.908→0.908, acc 0.908→0.898 —
     flat within noise, no regression.
   - Artifacts: `run11-chat-baseline`, `run12-chat-briefs`,
     `run13-flashlite-baseline`, `run14-flashlite-briefs` (.md/.json).

## Caveats

- `cf-llama-70b` (verify_worker's primary CF brain) is ACL'd out for the
  chaba litellm key — could not bench it from idc02. Rerun on idc03 with
  CF envs, or grant key access, to measure on the production brain.
- `--with-brief` stays opt-in; the flip decision is left to card comms
  (flash-lite delta argues for it in weak-brain lanes).
- briefs.json regenerates via `--corpus-briefs` when the corpus rebuilds.

## Verify

```bash
python3 scripts/ada-jobs/brief_builder.py --card <id>          # live bundle
python3 scripts/ada-jobs/brief_builder.py --card <id> --offline
python3 scripts/ada-jobs/verify_worker.py --once --card <id> \
    --with-brief --dry-run --base-url http://100.102.134.91:4000/v1 \
    --model chat --api-key-env LITELLM_KEY
python3 scripts/bench/card-judgment/score.py --entity ada --model chat \
    --api-key-env LITELLM_KEY --briefs scripts/bench/card-judgment/briefs.json
```
