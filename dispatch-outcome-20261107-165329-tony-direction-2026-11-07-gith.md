# Dispatch outcome — assessments-to-education-split-ssot-keep-113ca4

Tony direction 2026-11-07: github/website/repo assessments live in
Education (wiki lessons + docs/kb); SSOT keeps ONLY the verdict row +
pointer link. Research prose >~40 lines inside ssot.*.yml is a smell.
Retrieval had to exist BEFORE the split.

## 1. wiki->MDDB retrieval — DONE

- `scripts/board/board-api.py`: new `MDDB_LESSONS = "chaba-lessons"`
  (env `BOARD_API_MDDB_LESSONS` overridable) on the mddb-cms content
  plane (`MDDB` = 100.102.134.91:11027). `lesson_mddb_doc()` builds the
  one doc shape (key = `lesson-<md5(topic)>` — same slug as WP/wiki) and
  `_lesson_mddb_write()` mirrors every `/lesson` write (wiki-primary,
  dual and WP paths; also `op=delete` via `_lesson_mddb_delete`).
  Non-fatal: mirror failure degrades to `result["mddb"]` receipt.
- New read mode: `/lesson {op:list|get, source:"mddb"}` reads the mirror
  through the same door contract (`_read_lessons_mddb`).
- `scripts/board/lesson-mddb-backfill.py` (new): reads all lessons via
  `/lesson {op:list|get, source:wiki}` and upserts the identical doc
  into MDDB. Ran live: **135 docs in chaba-lessons, 0 failed**; verified
  via `/v1/search`. Retrieval now exists: agents query MDDB
  search/semantic_search on `chaba-lessons` (or the door's mddb mode).

## 2. Rule codified + lintable check — DONE

- `AGENTS.md` lesson-capture duty now names the retrieval surface and
  backfill; split rule gained the quantified smell + lint pointer.
- `scripts/ssot-prose-smell.py` (new): flags YAML string scalars >40
  lines where sentence-like lines dominate (code/config-shaped blocks
  skipped); exit 1 on hit; `--warn --lines --all --include-kanban`
  options. Post-clean status: **0 flagged**.

## 3. ssot/*.yml clean pass — DONE (6 files touched)

| file | prose moved | destination |
|---|---|---|
| docs/ssot/jobs/experiments/2026-08-26-gold-thb-usd-vector-analysis.yml | 93-line tuning ladder | lesson `gold-thb-usd-vector-analysis` (lesson-32518e35af20) |
| docs/ssot/jobs/ada/2026-10-10-speaker-id-owner-rebind.yml | 55-line decision rationale | lesson `ada-speaker-id-rebind-layers` (lesson-0eb6a7a7329c) |
| docs/ssot/focus-inbox/2026-10-16-033559-phonon2-audiocpp-stt-assessment.yml | 44-line deploy narrative | lesson `phonon2-audiocpp-stt-deploy` (lesson-227dddf98997) |
| docs/ssot/infrastructure/ssot.devin.maintenance.yml | 50-line runbook | `docs/kb/notebooklm-reauth.md` |
| docs/ssot/jobs/yt-dub/2026-10-07-yt-voice-dub-qc.yml | 71-line gate spec | `docs/kb/yt-dub-qc-gate.md` |
| docs/ssot/ssot.improvements.yml | 92-line impact rubric | `docs/kb/improvement-impact-scoring.md` |

Each keeps a ~6-9-line verdict summary + `see`/`ref` pointer. The 3 new
lessons are filed live (WP+dual -> wiki) and already mirrored into
chaba-lessons (136 docs total; one stray probe doc
`lesson-0eb6ad2333e2`, topic "Object Storage" body "v4", predates or
overlaps this work — left in place, flagged for cleanup).

## Trail

`docs/ssot/jobs/education/2026-11-07-lesson-mddb-mirror-and-ssot-split.yml`.

## Verify

- `python3 scripts/ssot-prose-smell.py` -> 0 flagged.
- `POST /v1/search {collection:"chaba-lessons"}` on mddb-cms -> 136 docs.
- `python3 scripts/board/board-api.py --selftest` -> ok.
- Post-deploy: `POST /lesson {op:list, source:"mddb"}` returns the
  mirror; new `/lesson` writes show `result.mddb.status: delivered`.

## Notes

- board-api code change is NOT deployed (dispatch rule) — takes effect
  when this branch merges + the service host pulls/restarts.
- Backfill was run against live services (per card spec): the MDDB
  collection is populated NOW even before the code change lands.
