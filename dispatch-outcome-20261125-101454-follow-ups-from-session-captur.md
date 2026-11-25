# Dispatch outcome — session-capture-d-1-follow-ups (OPS-1368)

Card: `session-capture-d-1-follow-ups-ledger-du-78e13f`
Branch: `dispatch/20261125-101454-follow-ups-from-session-captur`
Commit: `566ed29e07` (plus outcome-doc commit)

## Headline finding — two premise corrections

1. **The d1-metrics deliverables were never lost.** The prior dispatch
   (tony-macbook) exited ok but its checkpoint failed — report, job doc,
   SSOT Phase D refresh and dispatch-outcome were left dirty in its
   worktree. Recovered verbatim from
   `~/CascadeProjects/dispatch-wt-20261125-094816-goal-measure-repeat-ask-miss-r`
   on tony-macbook and landed here:
   `reports/capture/metrics-20261125.md`,
   `docs/ssot/jobs/kanban/2026-11-25-session-capture-d1-metrics.yml`,
   `dispatch-outcome-20261125-094816-goal-measure-repeat-ask-miss-r.md`,
   and the Phase D Refresh section in `ssot.knowledge-capture.yml`.

2. **The "missing" canonical ledger was on idc02 all along.** The d1 sweep
   checked idc03, tony-dell, tony-omen, con01, mn01, tony-macbook — but not
   idc02 (this host). `~/.local/share/chaba/capture/capture-ledger.yml`
   there holds the real 2026-11-23 baseline: 2220 entries plus the
   `applied:` block (`kanban:065d94f97e90` → wiki-login-polish), the four
   2026-11-23 metrics reports, an initialized `pointer-incidents.yml`
   (0 incidents), and 29 `info_find` run samples (vs the 3 the d1 report
   counted). **Decision: idc02 is the declared canonical capture host** —
   no migration needed; entries[] regenerate deterministically and the
   applied: history already lives there.

## Follow-up resolutions

1. **Ledger durability** — `chaba-capture-harvest` declared in
   `docs/ssot/infrastructure/ssot.jobs.yml` on **idc02** (05:30 daily,
   chained exec: `harvester.py` then `capture-metrics.py --out
   metrics-latest.md`); rendered to `systemd/generated/idc02/`. Declare +
   render only — install post-merge via
   `python3 scripts/render-jobs.py --host idc02 --ids chaba-capture-harvest --install`.
   Additionally `capture-apply.py` now mirrors every `applied:` audit to a
   card comm (board-api), so apply history survives ledger regeneration;
   comm failure is a non-fatal warning.
2. **pointer-stale-add adoption** — wired into the session-capture sweep
   skill and both info-find skills (`.devin` + `.agents`). Incidents are
   agent-reported at lookup time, deliberately not auto-detected; host-local
   telemetry, lazy init.
3. **resolved_ref semantics** — renamed to `top_result_ref` in
   `info_find.py` (it always meant "top citation exists"). Verified
   resolution is now a separate agent verdict:
   `info_find.py record --elapsed-ms N --resolved yes|no|unknown`.
4. **Repeat-ask register freshness** — AGENTS.md sweep duty gained a check:
   `ssot.repeat-asks.yml` stale_days >14 → decide zero-repeats (good) vs
   capture gap. Register itself left as-is (34d staleness unresolved but
   now monitored).
5. **Skill-path instrumentation** — `.devin/skills/info-find/info-find.mjs`
   now emits typed audit records (`kind:"plan"`/`"result"`, `elapsed_ms`,
   `resolved`) matching `info_find.py`'s schema — previously invisible to
   capture-metrics. `capture-metrics.py` time-to-find now splits
   `run_*` samples (local tool wall-time) from `session_*` samples
   (agent-reported end-to-end), and reports `top_result_pct` +
   `verified_resolved_pct` (legacy `resolved_ref` still accepted).

## Other changes

- `docs/ssot/jobs/session-summary/2026-11-25-c3-router-event-hooks.yml`:
  fixed pre-existing YAML break — `(PR #218)` had `#` starting a comment,
  truncating line 91; file was already unparseable before this session.
- `docs/ssot/ssot.knowledge-capture.yml`: Phase D Refresh updated with new
  metrics schema, revised thresholds (run median >5000ms /
  verified_resolved_pct <80% over ≥20 session samples), Follow-ups marked
  RESOLVED with per-item summary incl. the idc02 correction.
- `docs/ssot/CHANGELOG.md`: OPS-1368 entry.
- `docs/ssot/jobs/kanban/2026-11-25-session-capture-d1-follow-ups.yml`:
  job trail doc with decisions/delivered/verify/notes.

## Verification

- `render-jobs.py --check` → OK, 126 jobs / 8 hosts
- `capture-apply.py --self-test` → 8/8
- `capture-metrics.py --self-test` → 21/21
- `pytest tests/devnest/test_info_find.py` → 23 passed
- `pointer-stale-add.py --self-test` → 7/7
- YAML lint on all touched SSOT/job files → clean; `ssot-prose-smell.py` → 0 flagged
- `git status` clean on dispatch branch; no push, no master commit

## Remaining manual step

Install `chaba-capture-harvest` on idc02 after merge
(`render-jobs.py --host idc02 --ids chaba-capture-harvest --install`).
Until then the canonical ledger is simply stale (last harvest 2026-11-23);
a manual `python3 scripts/chaba/harvester.py` on idc02 refreshes it anytime.

lessons:
- "Absent on every reachable host" claims must enumerate the FULL host list — the d1 sweep skipped idc02 and wrongly declared the ledger lost.
- A dispatch that exits ok can still leave its deliverables uncommitted in the worktree; merge-sweep "no commits" means check the worktree before assuming loss.
- `reports/*` is gitignored except carve-outs — reports/capture/metrics-*.md needed `git add -f`.
- `(PR #N)` inside a YAML plain scalar is a comment trap — write `PR#N` or quote the scalar.
