# Dispatch outcome — session-capture-c4-harvester (OPS-1358)

## What was asked

Card `session-capture-c4-harvester`: "idempotent, bounded
harvester/index-refresh for pointer indexes/focus parity checks.
Depends: C.1-spec, C.2-router. Acceptance: rerun-safe; checkpointed;
audit records; no canonical duplication; dry-run mode."

## Dependency state found

- **C.1-spec**: contract text exists in PR #218 (OPEN, unmerged) — the
  "Capture Router Contract (Phase C.1)" section of
  `docs/ssot/ssot.knowledge-capture.yml`, including the
  "Harvester/index-refresh contract" bullet this job implements.
- **C.2-router**: not implemented (card still queued, no PR). The
  existing `scripts/chaba/capture-router.py` is the OPS-0016 read-only
  proposal router, not the C.1 envelope router. `capture-harvest.py`
  was therefore built self-contained: it *produces* the normalized
  events the future C.2 router will consume, so it does not depend on a
  router API.

## What changed

- **`scripts/chaba/capture-harvest.py`** (new, ~820 lines) — bounded,
  idempotent harvester/index-refresh per the C.1 contract:
  - Stream sources `card-comms`, `focus-inbox`, `dispatch-outcome`
    (the OPS-0016 approved set; card-comms/inbox reuse
    `harvester.py`'s filtered scanners) emit normalized events in the
    C.1 envelope. `event_id` = deterministic sha1 of `dedupe_key`
    (replay-safe); `event_type` v0 classifier covers the contract enum.
  - dispatch-outcome uses a local path-keyed scanner — the shared
    stem-only `source_id` could collide for same-named files under
    `docs/`.
  - Check sources: **pointer-index** (`path:`/`file:` refs in
    `ssot.index.yml`, `ssot.procedures-index.yml`, and
    `ssot.focus.current.yml` `sources[]` must resolve; compound
    `a + b` and label+path refs resolved via path-token extraction)
    and **focus-parity** (sessions/decisions required fields,
    append-only date order, session `decisions[].id` cross-checked
    against `ssot.technical-decisions.yml`; cue-action rows exempt
    from the `request` field per the CUE_RE convention).
  - Artifacts (only with `--write`, default out-dir
    `reports/session-capture/` — gitignored): `events.jsonl`
    (append-only, dedupe-key unique), `audit.jsonl` (run record +
    per-new-event records in the C.1 audit shape), `index.json`
    (pointer/index refresh artifact, upsert by `dedupe_key` with
    first_seen/last_seen — no canonical-body duplication, refs +
    bounded summaries only), `checkpoint.json` (per-source resume
    cursors that never regress under `--full`/`--since`/`--limit`),
    `report-<run>.md`.
  - **Dry-run is the default** — nothing is written without `--write`.
    `--since`/`--limit`/`--source` bound the scan; `--full` ignores
    cursors (dedupe still protects); `--no-checks`, `--stdout`,
    `--self-test` supported.
- **`scripts/chaba/harvester.py`** — one-char fix: dispatch-outcome
  `as_of` slice `[16:24]` → `[17:25]`; the old slice produced
  `-2026112` instead of `20261125`.
- **`docs/ssot/jobs/kanban/2026-11-25-session-capture-c4-harvester.yml`**
  — job record with verify evidence and lessons.

## Verification

- `capture-harvest.py --self-test` → 15/15; `harvester.py --self-test`
  → 5/5; `capture-router.py --self-test` → 13/13 (no regressions).
- `ssot-validate-refs.py` → only the pre-existing master error
  (`docs/ssot/jobs/devnest/2026-11-24-remote-eval-results-recovery.yml`),
  not caused by this change.
- Dry-run: 120 stream candidates (`--limit 40`/source) + checks in
  ~34 s, summary printed, zero files written.
- Write-mode idempotency (tmp out-dir): run1 95 new → incremental run2
  90 new (next window) → `--full` rerun 0 new/95 dup → `--full
  --limit 20` after `--limit 40` confirmed the checkpoint cursor does
  not regress. `events.jsonl` grew only by new dedupe_keys.
- Live check pass found 5 real findings: 2 dangling refs in
  `ssot.index.yml` (`ssot.mcp-debug.baselines.yml`,
  `ssot.apps.imagen2.yml`), 1 focus session missing ISO date
  (`sessions[14]`), 2 info-level session decision ids absent from
  `ssot.technical-decisions.yml`.

## How to verify / use

```bash
python3 scripts/chaba/capture-harvest.py --self-test
python3 scripts/chaba/capture-harvest.py                    # dry-run
python3 scripts/chaba/capture-harvest.py --write             # persist artifacts
python3 scripts/chaba/capture-harvest.py --write --limit 50 --since 2026-11-01
python3 scripts/chaba/capture-harvest.py --stdout --limit 5 # events JSON
```

Artifacts land in `reports/session-capture/` (or
`CHABA_CAPTURE_HARVEST_OUT`); a future timer/CI lane passes `--write`.
When C.2-router lands, it can consume `events.jsonl`/`index.json`
directly — the harvester is the producer side of the pipeline.

## Interpretations / notes for review

- "Pointer indexes" was read as the SSOT pointer surfaces
  (`ssot.index.yml`, `ssot.procedures-index.yml`, focus `sources[]`)
  plus the generated pointer index artifact — the job verifies refs
  resolve and maintains the index; it does not rewrite canonical files.
- "Focus parity" = schema/order/cross-ref consistency of the two
  focus logs the session-capture sweep appends to — not
  rendered-memory parity (that was answered "card-only" on DEV-0038).
- No canonical sink writes anywhere in this slice, matching the
  OPS-0016/OPS-0024 gated posture.

lessons:
  - "harvester.py dispatch-outcome as_of used stem[16:24] which yields
    '-2026112' — off-by-one slice; filename date starts at index 17."
  - "Checkpoint cursors must compare against the STORED cursor, not the
    resume cursor — --full nulls the resume cursor and would otherwise
    regress the checkpoint on bounded rescans."
  - "ssot.procedures-index.yml file: values are not all single paths —
    compound 'a + b' refs and 'AGENTS.md duties' label+path strings need
    path-token resolution, not exists() on the whole string."
