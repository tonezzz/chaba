# Dispatch outcome — media-inbox-report (KNB-0568)

Implemented `docs/kb/media-inbox-standard.md` end-to-end and deployed to
production on idc03. All five deliverables verified live.

## What changed

**chaba (origin/master → a6c2b8d3):**

- `scripts/ada/media-inbox-update.py` (new) — `manifest.jsonl` →
  `media-inbox` rollup + `media-<mid>` receipt leaves + `media-inbox-qc`
  per lane (mirrors `house-timeline-update.py` family shape,
  `trip-calendar.py` LANES/publish path). T1: manifest lines fold by
  `message_id` → one leaf per mid with a `redeliveries` note. T2: same
  `sha256` under a new mid → own leaf carrying `duplicate_of`. Never
  touches `*-extract` leaves (doc_read-owned). `--dry-run`, `--json`,
  per-lane `--lane tony|kk|kk-dev`, `reports-index` regen included.
- `scripts/ada/media-inbox-fixture.py` (new) — mifix-* seed/teardown used
  by the live scenario (`install`/`clean`).
- `docs/ssot/infrastructure/ssot.jobs.yml` + rendered
  `media-inbox-update-{tony,kk}.{service,timer}` — two 15m timers on
  idc03; env `MDDB_BASE_URL=http://100.102.134.91:11027/v1` (mddb-cms is
  tailnet-bound — `127.0.0.1` refused, fixed after first failed tick).
- `docs/ssot/ssot.procedures.yml` — media-inbox status defined→verified.
- `docs/ssot/jobs/ada/2026-10-13-media-inbox-family.yml` — job record.

**ada-pi (origin/main 6148f64 → d166794, deployed via `deploy-ada.sh idc03`):**

- `backend/line_relay.py` — `_archive_media` manifest lines carry
  `sha256`/`size`/`file_name`/`persona`/`caller` (hash + identity already
  in memory at archive time); journal entries carry `message_id`.
- `backend/tools.d/doc_read.py` — resolves canonical mid via manifest
  sha256 (T2 redirect → `duplicate_of`), checks `media-<mid>-extract`
  leaf **before** Gemini and writes it after (T3 cache — the leaf IS the
  cache); returns `cached`/`leaf`/`duplicate_of` in the result.
- `tests/scenarios-live/media_inbox.yaml` (new, smoke tier) — 5 turns.

**Lane attribution model** (not in the standard, decided + documented):
a manifest line belongs to the *receiving persona's* lane — relay stamps
`persona` at ingest; generator maps persona→lane. Legacy lines fall back
to `MEDIA_INBOX_CHATS` (kk's family group), so the 2 pre-existing lines
landed in `ada-cms-pages-kk`.

## Deploy / install state

- `deploy-ada.sh idc03`: pulled `d166794`, all 7 services restarted active.
- `~/CascadeProjects/chaba` on idc03 pulled to `a6c2b8d3`.
- `media-inbox-update-{tony,kk}.timer` installed + enabled on idc03
  (15m cadence). Manual service runs: tony → 3 leaves + rollup + qc
  (1 dup, 1 redelivery); kk → 2 leaves + rollup + qc (legacy lines).

## Verified

- Live scenario `media_inbox.yaml` vs `ada-ha-tony` :8002 — **PASS,
  0 failed expectations**: dup mid → one leaf (redeliveries note),
  same-bytes-twice → `duplicate_of: media-mifix-a`, doc_read twice →
  second call returns the cached extract leaf (`media-mifix-a-extract`),
  doc_read on dup mid → canonical extract + `duplicate_of`.
- Fixture: `media-inbox-fixture.py install --lane tony` on idc03;
  scenario cleanup needs `MDDB_BASE_URL=http://100.102.134.91:11027/v1`.

## Follow-ups / notes

- Fixture files + manifest lines persist on idc03 until
  `media-inbox-fixture.py clean` — the 15m timer will keep regenerating
  the mifix leaves; cleanup deletes the CMS docs only.
- Legacy manifest lines have no `sha256`/`persona` — T2 dedup only works
  for files received after this deploy (relay stamps sha256 at ingest).
- TG lane: standard says TG joins when its relay gains file ingest —
  `ada-tg-relay` doesn't archive yet; out of scope.
