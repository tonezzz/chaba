# Dispatch outcome — cms-page-standard + house-timeline family

**Card:** `cms-page-standard-house-timeline-family-6b7c77` (KNB-0562)
**Branch:** `dispatch/20261026-184108-define-the-standard-anatomy-me`
**Commit:** `f94e58b28`

## What changed

`docs/kb/cms-page-standard.md` already existed as a 2026-10-13 draft
covering anatomy / meta contract / quality bar / family pattern / publish
gate / checklist — but never mentioned `house-timeline`, and its domain
rule pointed at nav sections instead of canonical domains. Now:

- **Status → defined**, with pointers to the owning SSOTs
  (`ssot.cms.yml` identity/grouping, `ssot.apps.cms-reports.yml`
  provenance fields).
- **§2 meta contract:** `domain` values come from
  `ssot.cms.yml → meta.domain.canonical` (draft conflated nav sections);
  `parent` semantics spelled out — leaves and qc pages point at the
  family rollup, rollups at `reports-index`, external pages join a
  family by pointing `parent` at its rollup slug.
- **§4** rewritten as the parent/leaf/qc pattern + **adoption rule**
  (member set = `meta.parent=<rollup slug>`, one parent per leaf,
  rollup lists external leaves distinctly, qc counts them) + a dedicated
  **"The house-timeline family contract"** subsection: keys
  (`house-timeline` / `house-timeline-<entity>` / `house-timeline-qc`),
  source→sink `ada-ha-events-tony` (:11023, read-only) → `ada-cms-pages`
  (:11027), 72h window, ≥3-event leaf threshold, 25-leaf activity cap,
  `domain=home|meta`, `report_role=rollup|leaf|qc`, external-leaf join
  via `meta.parent=house-timeline`, index parity on write.
- **§5:** named **publish gate** (explicit ask + personal-data gate;
  family-internal leaves never public; sanitized derivative rollup for
  public surfaces) + **index parity on write** as a stated contract.
- **§6 checklist** extended: `report_role`, rollup→qc link, external-leaf
  adoption, `regen_reports_index`, canonical-domain check, publish gate.

`scripts/ada/house-timeline-update.py` **v1.1.0** — brought in line with
the contract it cites in its docstring:

- qc page `meta.parent`: `reports-index` → `house-timeline` (uniform
  family membership; matches trip-calendar + timer-timeline convention —
  `media-inbox-update.py` still stamps `reports-index`, a known
  divergence to normalize on its next touch).
- rollup footer now links `#/house-timeline-qc` (links both ways).
- added `regen_reports_index(MDDB_CMS, written_by=GENERATOR)` after its
  writes (dry-run guarded) — it was the only CMS producer missing
  reports-index parity.

`docs/ssot/jobs/cms/2026-10-26-cms-page-standard-house-timeline.yml` —
job trail with the qc-parent + domain-source decisions recorded.

## Verify

- `python3 -m py_compile scripts/ada/house-timeline-update.py` — clean.
- `--dry-run` against live mddb :11023 renders rollup + qc: 0 in-window
  events (newest `ada-ha-events-tony` doc is 2026-10-13 — the events feed
  itself looks stale, worth a separate look), and the 25 existing
  `house-timeline-*` leaf pages are correctly adopted as external leaves
  and counted in qc.
- No live publish run (dispatch worktree — no deploy).
- Done-condition met: `docs/kb/cms-page-standard.md` exists and
  explicitly documents the standard page anatomy + the house-timeline
  family integration contract.
