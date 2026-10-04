# Dispatch outcome — batch-review Sep29-Oct1 draft burst (ada-draft-backlog)

## What was found

The ~110 Sep29–Oct1 burst drafts in MDDB `ada-ha-bank-general` had **already
been reviewed** earlier the same day by the 12:15 dispatch
`triage the ada memory inbox` (task `20261004-121552-triage-the-ada-memory-inbox-on`,
finished ~13:04). Verified live against idc01 (tailnet `100.74.146.0:11023`):

- 0 docs with `status=draft` and `addedAt <= 2026-10-01` remain.
- The triage pass's decisions are stamped in doc meta — retracted docs carry
  `retracted_reason="inbox triage 2026-10-04: <reason>"`, superseded docs
  carry `superseded_by` links.
- The only live drafts were 6 post-triage inflow docs written today by
  `conversation_memory` (`extract-2026-10-04-*`).

## What this session did

1. **Audited the prior pass**: re-read all 89 `extract-*`/`distill/*` docs
   now marked active — decisions overwhelmingly sound (durable preferences,
   device facts, procedures). Retracted sample carries sensible reasons.
   Noted (not fixed): 41/54 superseded docs lack a `superseded_by` link —
   pre-existing gap.
2. **Reviewed the 6 live drafts** and applied decisions, plus 3
   correction-retracts of junk that slipped into active.
3. **Applied via `PATCH /v1/update`** (meta-only, no re-embed — same
   convention as `memory-staleness-sweep.py`), stamping
   `retracted_reason="batch-review 2026-10-04: <reason>"`. Nothing deleted;
   only `ada-ha-bank-general` touched.

## Applied decisions

**Promoted draft → active (5):**
- `extract-2026-10-04-519088cb6d-0` — TONY-TV displays CCTV feeds
- `extract-2026-10-04-e7afe759ba-0` — TVs: TONY-TV + TONY-TV Cast
- `extract-2026-10-04-e7afe759ba-1` — Noble Club feed viewed on TV
- `extract-2026-10-04-e7afe759ba-3` — Minted Metal gold-price source
- `extract-2026-10-04-e7afe759ba-4` — floodboard.org live flood maps

**Retracted (4):**
- `extract-2026-10-04-e7afe759ba-2` — knowledge-gap note (Amicon HA coords)
- `extract-2026-09-20-6d998cea19-1` — duplicate + meta-noise (Nobito PM2.5
  "location unknown in system memory"); covered by `extract-2026-09-24-c53d93f9e0-0`
- `extract-2026-09-23-9e52c57a61-0` — mis-transcription ("David memory" bank)
  + system-inventory noise
- `extract-2026-09-23-fb5912b6a8-0` — transient snapshot ("Rika sensors
  currently unavailable")

## Result

Bank `ada-ha-bank-general`: 230 docs — **109 active / 56 superseded /
64 retracted / 0 drafts** (plus 1 `probe-update-test` doc with no status,
pre-existing). Draft count after: **0**.

## Verify

```bash
curl -s -X POST http://100.74.146.0:11023/v1/search \
  -H 'Content-Type: application/json' \
  -d '{"collection":"ada-ha-bank-general","filterMeta":{"status":["draft"]},"limit":500}'
# -> []
```

## Trail

- Ledger: `docs/ssot/jobs/ada/2026-10-04-burst-draft-batch-review.yml`
- Card comms: dry-run counts posted before writes, final counts after.
- Card note says "verify draft counts trend down" — inflow is ~9/day via
  `conversation_memory` extracts; the remaining structural gap (nothing
  promotes drafts automatically) is a known follow-up the card already
  discussed (auto-promote was rejected; periodic batch-review stands).
