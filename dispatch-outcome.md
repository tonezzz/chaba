# dispatch outcome — flood-news CMS automation + CMS page normalization

## What was done

The flood-news automation already existed from earlier dispatches
(`flood-news-update.py` managed-block writer + `news-flood-fetch.py`
digest + systemd timers). This run verified it end-to-end, extended its
page coverage, and finished the CMS structure/memory-schema alignment it
exposed.

**Flood-news automation (timestamps + CMS updates — verified live):**
- `flood-report-pattaya-rayong` added to `flood-news-feeds.json`
  (pattaya/rayong/chonburi TH + EN feeds, interval_min 120,
  parent=flood-report) and populated — 6 timestamped items written,
  registry doc auto-created. Its thin-body (A1) and H1↔title mismatch
  (A3) audit failures are gone.
- `flood-report` children now list all three report leaves
  (nongdon-saraburi, pattaya-rayong, coordinates-rayong) in BOTH
  feeds.json and the live `ada-cms-automation` registry doc (the
  registry caches effective config and wins over the seed).
- `flood-report-nongdon-saraburi` force-run succeeded — the
  `last_status=error` health card was transient; cms-auto-health can
  auto-close it.

**CMS structure normalized to the memory-schema conventions:**
- `cms-normalize-meta.py --apply` — 137 docs updated (bank/scope/status/
  source/written_by/subject/attribute/valid_from/last_verified), 187
  already conformant.
- Tree fixes: `flood-hub-assessment` reparented to `flood-overview`
  (index children updated); `flood-report-nongdon-combined` archived
  (superseded merge artifact); orphan `ada-cms-automation/
  flood-report-nongdon` registry doc deleted; `translate-probe-de`
  marked stub.
- Writer contract (new `writer_contract` section in
  ssot.apps.cms-reports.yml): generators must merge existing meta and
  emit the full schema set. Applied to `news-flood-fetch.py`,
  `weekly-digest.py`, `kanban-cms.py`, `cam-wall-cms.py`,
  `cam-wall-roster-audit.py` (+sources/provenance footer), and
  `host-services-cms.py` (leaves no longer emit `children=[]` which
  serialized as a dangling `"None"` slug — R3).
- `cms-audit.py` — `mddb_search()` pagination (was `limit:200`, silently
  auditing only ~62% of the collection — flood/news pages weren't even
  being audited); dropped the server-side `kind=page` filter so docs
  missing kind are audited like the snapshot lane does; R6 no longer
  warns on index pages with children; `publish()` emits the R2 footer;
  `dev-kanban` added to A5_EXEMPT (renders arbitrary card text
  verbatim).
- `cms-normalize-meta.py` — paginated `list_docs`; `page_type` gains
  `-report\b` (flood-report-* leaves → `report`) and `digest` →
  `summary`.
- Live pages patched: `cctv-roster-audit` sources+footer,
  `tts-voice-catalog` footer reworded to match the R2 regex,
  `memory-ladder-standard` provenance footer, `services-*` leaves'
  `children=["None"]` dropped.

**Result:** live audit 317 pass / 6 fail — all 6 are baseline entries.
Snapshot regenerated (324 docs), baseline shrank 14 → 5 entries,
`baseline ratchet OK` (CI green). SSOT job doc:
`docs/ssot/jobs/ada/2026-10-05-flood-cms-automation-normalization.yml`.

## Verify

- `python3 scripts/ada/cms-audit.py` (live) → `317 pass · 6 fail` (all
  baseline)
- `python3 scripts/ada/cms-audit.py --file backups/ada-memory/
  ada-cms-pages.json --baseline scripts/ada/cms-audit-baseline.json` →
  `baseline ratchet OK — no new failures`
- `python3 scripts/ada/flood-news-update.py --all --dry-run` → fetches
  timestamped items for all 3 flood-report pages
- CMS page `flood-report-pattaya-rayong` now shows a
  `<!-- flood-news:auto -->` block with per-item publish timestamps

## Not done / notes

- systemd timers run from `~/CascadeProjects/chaba`, not this worktree —
  the writer fixes take effect on the next timer tick after merge.
- Remaining baseline fails are intentional (thin artifacts, A5/A6
  documentation false-positives) — documented in baseline `_why`.
