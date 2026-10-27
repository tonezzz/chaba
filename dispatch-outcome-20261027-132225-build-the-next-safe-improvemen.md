# education-maintenance-consolidated-report — outcome

**Card:** education-maintenance-consolidated-report
**Result:** shipped. One consolidated, read-only Education maintenance
report now joins the audit/drift/due surfaces; verified live on
2026-10-27 (92 lessons) with component-parity counts.

## What changed

- **`scripts/education-report.py` (new)** — the consolidator. One
  `/lesson` fetch (`op=list` + `op=get` per slug, the only door calls
  it ever makes) feeds all three component checks:
  `lessons_audit.audit_one` (R1–R5), `lessons_drift.audit_content`
  (source refs vs git), `lessons_due.review_bucket` (due/upcoming/
  learned). Emits `latest.json` (full machine rows), `latest.md`
  (concise tables — every flagged row carries its flag strings =
  the explanation), appends `history.jsonl` (trend), plus
  `<date>-education-maintenance.*` with `--dated`.
  Flags/options: `--fixture/--dump-fixture` (deterministic replay),
  `--date`, `--repo`, `--exceptions`, `--post board,tg` (only after
  verify pass + no holds), exit 0/1/2 for pass|hold|unreachable.
- **`scripts/lessons-drift.py`** — split `audit_lesson` into pure
  `audit_content` + fetch wrapper (byte-identical output; standalone
  run verified).
- **`scripts/lessons-due.py`** — extracted `review_bucket(meta, today)`
  (learned|due|upcoming); main loop uses it, same semantics.
- **`scripts/board/board-api.py`** — `do_lesson` now persists
  `meta.no_th` when a write skips Thai AND lands Thai-free (kept across
  Thai-free re-files; polish-preserve writes with Thai do NOT mark);
  `op=list` exposes `no_th`. Closes the lesson-polish documented gap.
  Selftest extended for the three no_th cases — `--selftest` passes.
- **`scripts/lesson-thai-exceptions.yml` (new)** — curated intentional
  no_th map, seeded with the 10 Thai-free lessons the 2026-10-24 polish
  pass treated as legit `--no-th`. The two speed-probe junk posts are
  deliberately NOT exempt — they stay flagged (delete is human-gated).
- **`tests/test_education_report.py` (new)** — 12 deterministic tests,
  no network: counts equal component functions on identical input,
  drift rows equal `audit_content`, buckets equal `review_bucket`,
  reproducibility (identical rows+digest), op-whitelist (no upsert/
  delete/touch ever sent — "no mutation in audit mode" proven at the
  boundary), hold gating, end-to-end artifact write + notify suppress.
  All pass.
- **`docs/ssot/infrastructure/ssot.jobs.yml`** — new job
  `chaba-education-report` (idc03, systemd, daily 07:50 — after
  lessons-due 07:30 and lessons-audit 07:40, both kept running),
  `condition_path` on the script so the unit skips until merge lands.
  Rendered units committed in `systemd/generated/idc03/`.
- **`scripts/board/kanban-commit.sh`** — `git add` loop +
  `SAFE_PULL_GENERATED_RE` extended to cover
  `docs/reports/education-maintenance/` so daily artifacts land via the
  single writer like other generated dirs.
- **`docs/ssot/jobs/education/2026-10-27-education-maintenance-report.yml`**
  — runbook: sections, holds, exit codes, verifier, manual ops.

## Live first run (2026-10-27, verify=pass, no holds)

92 lessons · 26 flagged · compliance **0.9643** (polish anchor
0.9307→0.9916, so slight regression since — new lessons + unfixed
backlog) · flags R1:overdue×5, R2:thin×2, R3:no-pointer×12,
R4:orphan×2, R5:consider-thai×12 · drift 3, source-gone 40,
no-repo-source 47 · due 14 / upcoming 78 / learned 0 · no_th exempt 10
· human-review-pending 51.

Parity check: standalone `lessons-audit.py` produced the identical flag
multiset on the same day (92/26).

`--post board,tg` demonstrated live: board comment landed on the card
(digest b4e31b30c8d97884); tg recorded `ok:false` — the relay is
idc03-loopback-only, unreachable from tony-macbook, fails soft by
design.

## Findings worth noting

- Dominant backlog is systematic, not per-lesson: ~28 source-gone rows
  point at `docs/tools/*.md` / `docs/kb/*.md` referenced by lessons but
  never committed (same root cause as the 2026-10-25 drift report).
  Fix = pointer pass via `/lesson` upsert or commit the docs —
  deliberately out of scope (observability card).
- 14 due reviews is Tony's real queue; listed in due_rows.
- 2 junk probes still pending human-gated delete (KNB-0830).

## Verify / reproduce

```bash
python3 -m unittest tests.test_education_report          # 12 tests
python3 scripts/board/board-api.py --selftest            # door patch
python3 scripts/education-report.py --out-dir /tmp/er    # live rerun
python3 scripts/lessons-audit.py                         # parity check
python3 scripts/render-jobs.py --check                   # manifest OK
```

Deploy note: merge lands the script + units; `render-jobs.py --host
idc03 --install` activates the 07:50 timer; board-api restart picks up
the `meta.no_th` persistence (report works either way — exceptions
file carries the pre-meta set).

lessons:
- WP lesson CPT `meta` doesn't persist write-time flags — `no_th`
  needed a door change + a curated file for the pre-meta set; check
  meta persistence first when building audit dimensions.
- kanban-commit only sweeps enumerated dirs — a generated-artifact dir
  must be added to its `git add` loop AND `SAFE_PULL_GENERATED_RE`, or
  daily artifacts sit dirty in the served checkout.
- Importing `lessons-audit.py` has import-time side effects
  (`makedirs(OUT)`, `TODAY` freeze) — set `LESSON_OUT` and pin
  `TODAY` when reusing it as a library.
