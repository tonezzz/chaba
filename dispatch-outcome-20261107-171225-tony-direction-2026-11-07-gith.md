# Dispatch outcome — assessments-to-education-split-ssot-keep-113ca4 (session 2)

Tony direction 2026-11-07: github/website/repo assessments live in
Education (wiki lessons + docs/kb); SSOT keeps ONLY the verdict row +
pointer link. Research prose >~40 lines inside ssot.*.yml is a smell.
Retrieval had to exist BEFORE the split.

This session was the second dispatch on the card — the first
(165329, merged as 61eb3685e) already shipped all three work items.
This session verified the landed state end-to-end, cleaned the one
flagged leftover, and wired the smell check into CI.

## Verified (all three work items hold)

1. **wiki->MDDB retrieval** — `chaba-lessons` collection live on
   mddb-cms (100.102.134.91:11027): 136 docs before cleanup, all 3
   split lessons retrievable by key/topic:
   `lesson-32518e35af20` (gold-thb-usd-vector-analysis),
   `lesson-0eb6a7a7329c` (ada-speaker-id-rebind-layers),
   `lesson-227dddf98997` (phonon2-audiocpp-stt-deploy).
   Dual-write code (`_lesson_mddb_write`, `source:"mddb"` reads) is in
   `scripts/board/board-api.py`; `--selftest` -> ok. Note: board-api
   code change is NOT yet deployed — mirror writes activate when the
   branch merges and idc03 pulls/restarts the service.
2. **Rule codified + lint** — AGENTS.md lesson-capture/split sections
   carry the retrieval surface + >40-line quantified smell;
   `scripts/ssot-prose-smell.py` -> **0 flagged** at default threshold.
3. **SSOT clean pass** — the 6 files cleaned in session 1 remain
   compliant (verdict + `see`/`ref` pointers in place; prose moved to
   lessons/kb). A deeper second pass at --lines 25 surfaced 37
   borderline values (25–39 lines) — reviewed: they are operational
   job records (`findings`/`measured`/`report.summary`, focus-inbox
   handoff texts), not assessment research; per the split rule
   "operational state stays in SSOT", they stay.

## New this session

- **Probe-doc cleanup**: deleted `lesson-0eb6ad2333e2` (topic "Object
  Storage", body "v4") from `chaba-lessons` — stray test doc flagged
  by session 1. Confirmed absent from both wp and wiki source stores
  (wp list: 135 legit lessons, no match; wiki page gone) so no
  backfill can resurrect it. Collection now **135 docs**.
- **CI enforcement**: `.github/workflows/ssot.yml` gained a step
  "Flag research-prose smell in SSOT (>40 lines)" running
  `python3 scripts/ssot-prose-smell.py` — the rule is now enforced on
  every docs/ssot change, not just lintable by hand. (pyyaml already
  installed by an earlier step in the same job.)
- **Trail updated**: `docs/ssot/jobs/education/2026-11-07-lesson-mddb-mirror-and-ssot-split.yml`
  gained a `verification_pass_2026_11_07_session2` record.
- **Incidental fix**: `docs/ssot/jobs/nest/2026-11-07-docpilot-v3-static-final.yml`
  was missing the required `title:` field (pre-existing failure from
  commit 952131844, would fail SSOT CI) — added; file now validates.

## Files touched

- `.github/workflows/ssot.yml` (+2 lines: CI step)
- `docs/ssot/jobs/education/2026-11-07-lesson-mddb-mirror-and-ssot-split.yml` (verification block)
- `docs/ssot/jobs/nest/2026-11-07-docpilot-v3-static-final.yml` (+title)
- `dispatch-outcome-20261107-171225-tony-direction-2026-11-07-gith.md` (this file)

## Verify

- `python3 scripts/ssot-prose-smell.py` -> 0 flagged.
- `curl -X POST http://100.102.134.91:11027/v1/search -d '{"collection":"chaba-lessons","limit":200}'` -> 135 docs.
- `python3 scripts/board/board-api.py --selftest` -> ok.
- Post-merge: `POST /lesson {op:list, source:"mddb"}` on idc03 returns
  the mirror; new `/lesson` writes show `result.mddb.status: delivered`.

## Known follow-ups (not blocking)

- board-api mddb-mirror code still undeployed (dispatch rule) — takes
  effect on merge + service restart on idc03.
- 37 sub-40-line prose blocks inventoried above; if Tony wants a
  tighter bar, `--lines 25` on the same script lists them.
