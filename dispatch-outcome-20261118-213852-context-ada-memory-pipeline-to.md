# Dispatch outcome — memory-extract-merge-proposals

## What changed (commit 8e7b3cd9c4 on dispatch/20261118-213852-…)

- **New `scripts/ada/memory-merge-proposals.py`** — weekly recommend-mode job.
  For every writable bank it lists active canonicals + `source=extract`
  drafts from the last 14d, vector-searches each draft against its own
  collection, and proposes merges for hits scoring **0.82–0.95** on the
  same subject/attribute (missing meta → score-only, flagged
  `weak_join`). Suggested action is deterministic: `reject` when the
  draft is a restatement (containment/jaccard ≥0.9), `supersede` on
  scope mismatch, else `update-in-place`. **No canonical writes ever in
  propose mode.**
  - Output: `ada-cms-pages/memory-merge-proposals` (kind:report, managed
    block, reports-index regen) + board comment + job-result event +
    `--emit` event when proposals are open.
  - Apply path (manual): `--resolve <id> --action
    update-in-place|supersede|reject [--text wording]` performs real
    supersede-link writes (supersedes/superseded_by, last_verified bump,
    draft status=superseded + merge_review=applied; reject stamps
    merge_review=rejected so it's never re-proposed). A reconcile pass
    adopts resolutions applied outside `--resolve`.
  - Metrics: `~/.cache/ada-memory-merge-proposals.json` — per-pair
    lifecycle + run log; rolling 90d acceptance in every report.
- **`ssot.jobs.yml`**: `ada-memory-merge-proposals` — idc03, Sun 10:30
  (after hand-installed `ada-memory-distill.timer` 09:45), persistent,
  20m, `--emit`, condition_path on the script. Rendered units committed
  under `systemd/generated/idc03/`.
- **`ssot.audit.hosts.yml`**: timer added to idc03 census.
- **`ssot.apps.ada-memory-progress.yml`**: done-task line.
- **`tests/ada_memory/test_memory_scripts.py`**: `TestMergeProposals` —
  9 tests (candidate filter, same_slot, suggest_action, id stability,
  footer strip, reconcile incl. unscanned-collection guard, rolling
  acceptance). **34/34 pass.**
- **Job doc**: `docs/ssot/jobs/ada/2026-11-18-memory-merge-proposals.yml`.

## Verified live (from idc02, prod MDDB :11023 / CMS :11027)

- `--dry-run --draft-days 45`: **3 real proposals** from 131 drafts —
  band + subject/attribute filtering works end-to-end.
- Resolve path exercised on `ada-ha-bank-dev-scratch` (staging): seeded
  canonical + drafts, `--resolve … reject` → merge_review=rejected;
  `--resolve … supersede` → new canonical with supersedes link,
  canonical + draft marked superseded/applied. Test docs deleted.
- First report **published**: `ada-cms-pages/memory-merge-proposals`
  (0-proposal report — see finding) + card comment posted.

## Findings / caveats

- **Extract inflow is stalled**: newest `source=extract` draft in any
  bank is 2026-10-17 (~1 month old) → 14d window yields 0 proposals.
  Carded on the board comment; if proposals stay 0, check
  memory-distill writes / lane-retention extract merge before the
  acceptance gate means anything.
- **MDDB commit-but-drop under embed stress**: while the embed chain
  was capped (OR daily 5000 + paid hourly 150 + free Gemini), writes
  and even meta PATCHes committed server-side but dropped the HTTP
  response. Script hardened: `update_meta` verifies via `/get` before
  re-patching, CMS `/add` verifies content after transport failure,
  supersede reuses a same-day partial-apply doc.
- Install step remaining on idc03 post-merge:
  `render-jobs.py --host idc03 --ids ada-memory-merge-proposals --install`

## How to verify

```
python3 -m unittest tests.ada_memory.test_memory_scripts   # 34 pass
python3 scripts/render-jobs.py --check                     # manifest OK
python3 scripts/ada/memory-merge-proposals.py --dry-run    # read-only scan
python3 scripts/ada/memory-merge-proposals.py --dry-run --draft-days 45 --no-publish
# page: ada-cms-pages/memory-merge-proposals; card comms on
# memory-extract-merge-proposals
```
