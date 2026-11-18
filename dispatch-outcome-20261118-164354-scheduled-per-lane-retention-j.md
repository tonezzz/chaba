# Dispatch outcome — ada-transcript-archive-retention (ADA-0478)

## Result: implementation complete on branch `dispatch/20261118-164354-scheduled-per-lane-retention-j` — ready for merge + timer install

This card had ~5 prior failed dispatch attempts (rate limits, zombie claims).
The salvageable work lived on `fix/ada-0478-lane-retention` (draft PR #182,
c86b904 + review-state doc commit). This session merged that branch into the
dispatch branch cleanly and applied Tony's FINAL policy decision recorded on
the card 2026-11-18 16:16: **ada-pi-pwa → dev lane** (supersedes the earlier
"exclude" answer on request `pi-pwa-lane-classification`; the other open
request `4-policy-defaults` was answered "proceed" = all starred defaults).

## What the merged work delivers (per card spec)

`scripts/ada/lane-retention.py` — weekly per-lane job, 3 duties:
1. **Transcript → NotebookLM deep archive**: `<date>-<sid>.md` files older
   than 2d on lane hosts are attributed via `meta.session_id` in
   `ada-ha-recall-summary-<lane>`/`ada-ha-actions-<lane>` MDDB collections
   (the durable sid→lane map) + sparse `journalctl session=` lines, then
   uploaded to the lane's notebook via `ssh mn01 podman exec notebooklm-mcp
   nlm source add`. Unattributed transcripts stay local (no cross-lane
   leakage). Dedup: `~/.cache/ada-lane-retention.json` + title scan.
2. **Ops TTL**: `ada-ha-events-*`/`ada-ha-snapshots-*` swept at 30d on BOTH
   mddb-ops (:11025) and leader (:11023) via `prune-old-docs.py` (extended
   to all 7 instances, dual-base). `ada-ha-actions-*` deliberately not pruned.
3. **Extract supersede-merge**: `extract-*` docs grouped by subject, merged
   by Gemini into canonical `<bank>/<slug>` docs (superseded_by provenance,
   source_keys; new canonicals draft unless all sources active — human
   review gate preserved; lane-scoped extracts never fold into shared
   canonicals).

4 weekly user timers on idc03 (rendered from ssot.jobs.yml): dev 04:00,
tony 04:15 (--include-shared), kk 04:30, michael 04:45 Sunday. Each run
posts a card comment + `ada-ha-events-<lane>` ops-event + chaba job-result.

## Changes made THIS session (commit 22faaba601)

- `lane-retention.py`: dev lane units += `ada-pi-pwa`.
- `ssot.jobs.yml`: ada-retention-dev `on_calendar` 05:00 → **04:00** (before
  tony) + note. Rationale: pi-pwa ran with `ADA_INSTANCE_ID=tony`, so its
  recall sids sit in tony's collections — journald is the ONLY dev-attributing
  signal and dev must claim before tony's 04:15 run for those sids to tag dev.
- Regenerated `systemd/generated/idc03/ada-retention-dev.timer` via
  `render-jobs.py`.
- `test_lane_retention.py`: inventory test updated for the 3-unit dev scope.
- `docs/ssot/jobs/ada/2026-11-17-lane-retention.yml`: decision + known-gap
  documented (pi-pwa sids only in tony collections still tag "(tony)" — same
  shared notebook, unavoidable), processing → ready.

## Verification

- `pytest tests/ada/test_lane_retention.py` — **24/24 pass**
- `render-jobs.py --check` — OK 110 jobs, 8 hosts
- `ssot-validate-all.mjs` — **5016/5016 valid**, 0 errors (176 warnings, baseline)
- `ssot-validate-refs.py` — only the 2 PRE-EXISTING verify.py ref errors
  (ada-docs-search-drift, ops-event-plane-split-brain-audit) — same as master
- `ssot-prose-smell.py` — 0 flagged
- Broader `pytest tests/ada tests/ada_memory` — 35 failures, ALL
  `ModuleNotFoundError: httpx` in unrelated map/place tests (env gap, not this change)

## NOT done (deliberately — out of dispatch scope)

- **No push** to origin (dispatch rule), no timer install, no live run —
  the job doc itself notes "No timer install, transcript upload, MDDB
  deletion, or Gemini merge in this task." Deployment path after merge:
  `scripts/render-jobs.py --host idc03 --ids ada-retention-dev,ada-retention-tony,ada-retention-kk,ada-retention-michael --install`
  on idc03, then a `--dry-run` per lane before the first Sunday.
- PR #182 (`fix/ada-0478-lane-retention`) is now redundant — its content is
  fully contained in this branch plus the pi-pwa resolution; close it after merge.
- ada-pi-pwa.service is already retired/removed (done 2026-11-17); its
  journald history persists for sid attribution.
