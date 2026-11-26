# Dispatch outcome — session-capture-d1-metrics (2026-11-25)

## What was done

Measured the four Phase D capture signals read-only and refreshed the SSOT
thresholds/tuning section.

- Ran `scripts/chaba/harvester.py` into the worktree
  (`reports/capture/`) because the canonical ledger
  `~/.local/share/chaba/capture/capture-ledger.yml` — including the
  `applied:` audit block from the 2026-11-23 baseline — is absent on every
  reachable host (idc03, tony-dell, tony-omen, con01, mn01, tony-macbook).
  Fresh ledger: 3679 proposals / 2778 new entries.
- Ran `scripts/chaba/capture-metrics.py --ledger reports/capture/capture-ledger.yml`
  → `reports/capture/metrics-20261125.md`.
- Generated 3 real `info_find.py run` samples so time-to-find is measured,
  not `unmeasurable` (median 1647ms, mean 2203ms, max 3320ms).
- Updated `docs/ssot/ssot.knowledge-capture.yml` with a "Phase D Refresh
  (2026-11-25)" section: measured values, the ledger-durability gap, and
  recorded tuning thresholds.
- Filed follow-up card **OPS-1368**
  (`session-capture-d-1-follow-ups-ledger-du-78e13f`) for the five gaps
  found (ledger durability, pointer-log adoption, resolved_ref semantics,
  register staleness, info_find adoption).
- Job trail: `docs/ssot/jobs/kanban/2026-11-25-session-capture-d1-metrics.yml`.

## Results

| Signal | Status | Value |
|---|---|---|
| Repeat-ask rate | measured | 9 topics / 15 asks / 3 open; last entry 2026-10-22 (34d stale) |
| Miss rate | measured | 0 since instrumentation 2026-11-23 |
| Stale-pointer | proxy | 35 candidates >30d (oc-note 32, ssot 3); no incident log exists |
| Time-to-find | measured | n=3, median 1647ms; resolved_pct 100% (top-citation caveat) |
| Matrix precision | measured | 100% on fresh ledger (8 kanban creates, 0 filed-artifact) vs ~2% pre-fix |

## How to verify

```
python3 scripts/chaba/capture-metrics.py \
  --ledger reports/capture/capture-ledger.yml \
  --out /tmp/metrics-check.md
python3 -c "import yaml; yaml.safe_load(open('docs/ssot/ssot.knowledge-capture.yml'))"
python3 scripts/ssot-prose-smell.py   # 0 flagged
```

## Notes

- Read-only posture kept: harvester/capture-metrics/info_find run are all
  non-canonical writes; the only canonical-ish writes were the SSOT YAML
  edit (worktree) and the OPS-1368 card via board-api.
- No fake events: proxy stays labelled proxy; the fresh ledger's missing
  `applied:` history is disclosed as a caveat in both report and SSOT.
- Card `session-capture-c2-router` was still queued; not a blocker since
  metrics consume the ledger + SSOT registers, not the router.

lessons:
- The canonical capture ledger lived only under ~/.local/share on a host
  that no longer has it — local-telemetry "canonical" stores need a
  declared durable home or they silently evaporate.
- info_find audit.ndjson files predate the kind:"run" schema; only
  `info_find.py run` writes total_elapsed_ms — plan/result records are not
  measurable for time-to-find.
- resolved_ref in the time-to-find audit means "top result has a
  citation", not "correct answer found" — resolved_pct will read ~100%
  even on bad runs until relevance is checked.
