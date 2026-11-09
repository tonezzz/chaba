# dispatch outcome — primer-efficacy-measurement (OPS-1270)

## What changed

- `scripts/board/primer_efficacy.py` — new read-only analyzer. Rebuilds
  dispatch events from card comms across BOTH lanes (kanban-dispatch
  `dispatched <task> on <repo>` and runner-agent `started devin-task-*
  (dispatch)`), pairs `primer injected N lesson(s)` lines to their
  dispatch, classifies post-injection failure events by the primer's own
  keyword signature (MIN_SCORE=2), and compares card-level
  verified/merge rates across pre-era / post-primed / post-unprimed /
  post-runner cohorts. Includes a live health probe (`lp.build()` on
  this corpus), self-seeding stats, and `--json`/`--md` output.
- `reports/primer-efficacy-2026-11-09.md` — full computed tables,
  verdict, A/B design (gitignored → force-added).
- `docs/ssot/jobs/kanban/2026-11-09-primer-efficacy.yml` — job doc with
  findings + followups.

## Result / evidence

- **Verdict: CONTRADICTED.** 15 injections ever (all 8-line), last at
  2026-10-11 06:15. Coverage: 15/41 kanban-lane (37%), 0/893 runner-lane
  (no primer code path — ~96% of traffic), 1.6% overall.
- **Root cause of current death**: `lp.build()` raises
  `AttributeError: 'str' object has no attribute 'get'` on the live
  corpus — `_comms_candidates` assumes dict comms; `kraut-rain-events`
  + `kraut-weather-bakeoff` carry plain-string entries. Fail-open +
  log-only-on-success = silent month-long outage. With strings tolerated
  it returns 8 lines — the crash is the sole current blocker.
- **Repeat-failure**: 8/12 (67%) post-injection failures had a matching
  injected lesson — matching works when the primer runs (the recurring
  `test_calendar_providers` gate failure was literally warned about).
- **Success rates** (observational, confounds flagged): verified 24%
  pre-era vs 100% post-primed (n=13) vs 88% unprimed vs 67% runner;
  era-fair `merged` comparator: 33% / 77% / 82% / 76% — no visible lift.
- **Self-seeding**: only 22/311 post-launch outcome docs (7%) carry the
  `lessons:` block.
- Spot-checks verified against card YAML: ada-acl-explain,
  ada-deploy-gate-tests (warned-failure, literal), line-file-doc-ingest
  (dead).

## Caveats / how to verify

- `python3 scripts/board/primer_efficacy.py --md` (or `--json`) — runs
  clean, ~90s on the full corpus.
- The 10-13→10-16 zero-injection window predates the kraut string comms
  — same invisible signature, mechanism unproven (noted in job doc).
- A/B design in the report requires first: fixing the string-comms
  crash, wiring primer into the runner-agent lane, and logging
  zero-injection lines — carded as followups in the job doc.

lessons:
  - fail-open advisory feature + log-only-on-success observability = silent death; the primer injected nothing for ~a month and nothing could see it — always log the zero case
  - card comms are not guaranteed dicts — plain-string entries exist (kraut-* cards) and crash any scan assuming .get(); tolerate or per-item-try everywhere
  - two dispatch lanes write different comms markers ("dispatched X on repo" vs "started devin-task-X on host (dispatch)") — measuring only lane one misses ~96% of traffic
  - 'verified' is a post-era stamp — era comparisons must use merge-comms presence, not action.verified
