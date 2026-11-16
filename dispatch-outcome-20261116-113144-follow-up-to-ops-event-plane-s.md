# Dispatch outcome — ops-event-plane-split-brain-fix

**Branch:** `dispatch/20261116-113144-follow-up-to-ops-event-plane-s`
**Commit:** `4f9b8e12eb` (25 files, +360/-58) — committed locally, NOT pushed
**Trail doc:** `docs/ssot/jobs/infrastructure/2026-11-16-ops-event-plane-repoint.yml`

## What was done

The audit listed 10 surfaces; a repo sweep found **19** still handling
ops-plane collections on leader :11023. All repointed to mddb-ops
`http://100.123.163.11:11025` via the `MDDB_OPS_URL` convention
(house-timeline precedent).

**Decision per surface** (repoint vs keep-on-leader):

- **Repoint, ops-only** (only MDDB use is ada-ha-events-*): ops-error-posts,
  host-loads, kanban-dispatch, lesson_qc, key-watch, ops-digest,
  ops-report (leader fallback removed), budget-watch.
- **Split, mixed**: embed-probe and vector-reindex keep the leader for
  vector-search/stats/reindex (mddb-ops is no-embed — the probe must
  stay), ops-event emits move. memory-standard keeps banks/vector-search
  on leader, events read+write move (its phantom/confirm_strip budget
  check was reading frozen residue — silently dead since 10-23).
  recall-canary same split. render-report-feed keeps the devin-handoff
  job ledger on leader, ops-events read moves. session-audit moves
  ops-events read AND ada-ha-scenario-reports read/write (declared ops
  collection). house-distill moves snapshots+events reads; bank write
  stays leader.
- **Dispatcher fix**: `_base()` in kanban-act and report-ada-debug gained
  an `_OPS_COLS` prefix rule covering all ops collections.
- **report-api**: `REPORT_EVENTS_URL` falls back to `MDDB_OPS_URL`,
  defaults :11025.
- **prune-old-docs**: ada-ha-events/snapshots retention was sweeping the
  leader's frozen residue while live :11025 copies grew unbounded
  (12.6k docs). Now sweeps `MDDB_ADA_OPS_URL` :11025 — distinct env name
  because host-logs tooling reuses `MDDB_OPS_URL` for a *different*
  store (idc03 :11026); collision documented in the kb.
- **Bug found en route**: session-audit's `regen_reports_index` scanned
  :11023's stale 9-doc ada-cms-pages; now `MDDB_CMS` (:11027).
- **Deploy coverage**: ssot.jobs.yml env pins `MDDB_OPS_URL` +
  transitional `MDDB_BASE_URL`→ops on session-audit, chaba-host-loads,
  ops-error-posts (pre-repoint builds on unsynced checkouts land right);
  generated units re-rendered. Units not in jobs.yml pick up the new
  code default on checkout sync.

## Verified

- `py_compile` clean on all 19 scripts; `ssot.jobs.yml` yaml.safe_load OK;
  `ssot-prose-smell.py` 0 flags.
- Selftests PASS: ops-error-posts, session-audit, key-watch, budget-watch;
  test_kanban_act.py 18/18.
- Routing asserts: ops collections → :11025, ada-cms → :11027, banks → :11023.
- Live reads on :11025: ops-report pulled 3 events; ops-digest queried OK;
  prune --dry-run swept the real 12,636-doc collection.
- Residual sweep: zero files reference ada-ha-events with a :11023-only base.

## Open items

- **Board request** `backfill-decision-needed-repoint-branch-26e335`:
  copy post-10-23 chaba-side ops-event docs from leader → :11025?
  (recommended a=copy / b=skip / c=copy+delete-residue — unanswered at
  session end.)
- **Follow-up card recommended**: ~7 more surfaces (nest-train-loop,
  nest-overview, chaba-audit, report-distill, bank-router-probe,
  bench-edge-cms, embed-space-eval) still hit leader for
  ada-ha-scenario-reports — same fix class.

## How to verify after merge

1. `python3 scripts/ops-digest.py` — should report from :11025
   (currently "all quiet" — last ops-event ~Nov 6).
2. Trigger a host transition or run memory-standard — the ops-event doc
   should appear on `:11025/v1/search collection=ada-ha-events-tony`,
   NOT on :11023.
3. `git diff origin/master -- scripts/` — every `MDDB_OPS_URL` default
   is `:11025`; no ada-ha-events path defaults to `:11023`.
