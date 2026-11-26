# Dispatch outcome — ada-smoke-regressions-20261107 (attempt 2)

## What I did
Re-triaged all 4 smoke failures against CURRENT data — the suite kept running
hourly on ada-dev (tony-omen :8005), so verdicts use today's 2026-11-26 reports
(MDDB `ada-ha-scenario-reports`), not just the Nov-7 originals. Full trail:
`docs/ssot/jobs/ada/2026-11-26-smoke-regressions-triage.yml`.

## Per-failure verdicts
1. **ada_opencode_control t3 — expectation rot.** The ask→respond→dispatch
   approval handshake (ada-voice 9557656/e7cde59/3425d27) now legally requires
   a preflight-minted approval_receipt before `ada_opencode_dispatch` may be
   called. Turn1's preflight failed and turn3 names a nonexistent card with no
   receipt — refusing and narrating (what she did) is the CORRECT behavior.
   Scenario still expects a bare dispatch call + "card not found".
2. **auto-report-worthy t1 — expectation rot.** The canonical source moved to
   the `auto-report` CMS page (ada-cms-pages, written by scenario-benchmark.py,
   which literally tells Ada to read it for "anything to report?"). She
   answered with real current data via `cms_read` x3 — the designed CMS-first
   path. Expectation still demands `ada_memory_search`.
3. **cms_public_url_lane t4 — expectation rot + real hygiene bug.** Confirm-
   gate fix (07119b1) verified live — publish turns now pass. Remaining fail:
   scenario asserts kk-lane artifacts but runs on ada-dev (tony lane), so
   `/tony-ha/kk-site-test.html` is the CORRECT URL. Side effect: cleanup
   targets `ada-cms-pages-kk`, so the tony-lane page is never deleted —
   `kk-site-test` has been `public=true` and live on surf-thailand.com since
   2026-10-11 (~6 weeks). Needs a delete/unpublish decision.
4. **cms-translate t4-5 — mixed.** `'lang': 'th'` never appears in any
   tool_result and the th doc is untouched since Oct-14 — her Thai publish
   never persisted (probable arg-shape miss re-hitting the slug:en pending).
   SEPARATE REAL BUG found: `scenario-live.py run_cleanup` posts `/delete` to
   `MDDB_BASE_URL` (ops plane :11023) but `ada-cms-pages*` live on the cms
   plane (:11027) — cleanup 404/400s for every cms_* scenario, leaving test
   litter. `cms_get_page`→`cms_read` merge still satisfies calls via alias.

## Result
No code changed in chaba (fix targets are ada-voice scenario YAMLs +
scenario-live.py cleanup routing — different repo). Deliverable is the
verdict trail above; all 4 are scenario/expectation issues except the
runner cleanup plane bug and the stray public page, both filed as actions.

## How to verify
- Reports: `report/{ada_opencode_control,auto-report-worthy,
  cms_public_url_lane,cms-translate}-20261126-*` in MDDB ada-ha-scenario-reports.
- Stray page: `ada-cms-pages/kk-site-test` meta public=true, updated 2026-10-13.
- Runner bug: `scripts/scenario-live.py` ~line 1532-1570 vs
  `scripts/ada/nest-overview.py::_base()` plane routing.

lessons:
- Card comms text is truncated ~400 chars by board-api — full verdicts must live in a committed file, not comms.
- MDDB has multiple planes (:11023 ops, :11027 cms); collection-prefix routing matters — scenario-live.py cleanup lacks it.
- "Still failing" ≠ "unfixed": re-read the newest report before re-diagnosing — signatures change weekly.
- Scenario YAMLs encode lane assumptions (kk) that silently rot when the suite's target instance changes.
