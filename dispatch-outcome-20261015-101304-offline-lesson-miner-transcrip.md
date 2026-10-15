# Dispatch outcome — Offline lesson miner: transcripts -> lesson CPT

Card: lesson-transcript-miner (OPS-0694) · Runner: idc02 · 2026-10-15

## What was built

`scripts/ada/lesson-miner.py` — nightly batch miner implementing the
approved card design (zero per-session prompt tokens, free-first model):

1. **scan** — `~/.local/share/ada/transcripts/*.md` on the ada runtime
   host, size-deduped against `~/.local/share/ada/lesson-miner-state.json`
2. **filter** — mechanical question-turn detection (no LLM): `?` /
   EN question starters / Thai question markers; device commands and
   <15-char turns excluded; each question paired with the following Ada
   turn(s) as its answer
3. **classify** — ONE `gemini-3.5-flash-lite` JSON call per run keeps
   durable knowledge Q&A (topic + intro/working/deep level), drops
   commands/chit-chat/private asks
4. **draft** — one call per kept topic (cap 4/run) writes a standalone
   HTML lesson from the FULL transcript (richer than the voice answer;
   strips personal specifics, flags uncertainty)
5. **file** — subprocess `scripts/lesson-add.py --source voice` (slug
   upsert on the WP lesson CPT + automatic Thai translation)

Dedup: filed slugs recorded in state so re-asked topics don't burn draft
calls (`--refile`/`--reprocess` overrides). Board comment posts only
when lessons were filed or filing failed (quiet-when-empty). Key
resolution: env `GEMINI_API_KEY_FREE`/…/secrets env files;
`GEMINI_BASE_URL` honored via `gemini_rest` for optional gateway routing.

## Files changed

- `scripts/ada/lesson-miner.py` (new, ~430 lines, +x)
- `tests/ada/test_lesson_miner.py` (new — 11 tests)
- `docs/ssot/infrastructure/ssot.jobs.yml` (`ada-lesson-miner` job:
  idc03, systemd, daily 04:40, timeout 20m, OnFailure ada-report-fail)
- `systemd/generated/idc03/ada-lesson-miner.{service,timer}` (rendered)
- `docs/ssot/jobs/ada/2026-10-15-lesson-transcript-miner.yml` (job doc)

## Verification

- `python3 -m unittest tests.ada.test_lesson_miner` — 11/11 green
  (EN+TH question detection, command/tiny exclusion, Q→A pairing,
  slug parity with lesson-add.py, state roundtrip/corrupt recovery)
- Full `unittest discover` — no regressions; only pre-existing
  `import pytest` errors in 6 unrelated test modules (pytest not
  installed on this runner)
- `render-jobs.py --check` — 54 jobs OK; rendered idc03 units verified
- `ssot-validate-all.mjs` — 2408 files, 0 errors
- End-to-end smoke with stubbed `gemini_rest` — candidate → classify →
  draft path exercised

## Not done / follow-up

- **Unit not installed on idc03** (dispatch rule: no deploy). After
  merge: `scripts/render-jobs.py --host idc03 --install`, enable the
  timer, and eyeball the first run's lesson quality (`--dry-run` first
  is safest).
- Requires on idc03: `~/.config/secrets/wp-boards.env` (present per
  AGENTS.md note) + a GEMINI key — free tier suffices.
- Card's lossy-recall fallback (one-line Ada instruction + intake comm)
  deliberately not implemented — evaluate the first week of mined
  output first.

## Lessons

- `docs/ssot/infrastructure/ssot.jobs.yml` + `render-jobs.py` is the
  SSOT path for scheduled jobs — add a manifest entry and render, don't
  hand-write units.
- `gemini_rest.generate_json` + the session-report.py secrets chain is
  the canonical free-first LLM call pattern for batch scripts.
