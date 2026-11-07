# Dispatch outcome — wiki education step 5 (activation verify + due/index job)

Card: `wiki-member-knowledge-surface-migrate-wp-3a1cf2` (6th dispatch;
earlier runs shipped the plan, 2a/2b tooling, live migration of 124
lessons, and the step-4 read door). Branch
`dispatch/20261107-114216-idea-2026-11-06-tony-chat-migr` — 8 files
modified + 1 new job doc.

## What this session found and did

**Step 5 verified live — activation already happened.** The deployed
idc03 door already serves `/lesson source=wiki` (127 rows, `source`
echoed), so the merge+restart gate had closed before this dispatch.
`scripts/lessons-due.py --dry-run` renders `Education:Due` +
`Education:Index` from the live wiki corpus; the real `--dest wiki`
run wrote `Education:Due` rev=186 and `Education:Index` rev=187 via
`/wiki/page`. Anon pretty-URL read → 404: the Lockdown boundary on
`Education:` holds.

**Bug 1 — actor 400 (would have broken the daily job).**
`lessons-due.py` sent `from: "lessons-due"`; the door's login
allowlist is `ada|chaba|devin|tony`, so every door call 400s —
verified live. The test asserted the invalid value, so it shipped
green. The synced `chaba-lessons-due` 07:30 timer on idc03 fails at
`fetch_rows` on this build (both dests skipped). Fixed to `chaba`
(the merge-sweep convention for job scripts).

**Bug 2 — generated pages counted as lessons.** The door's
`_read_lessons_wiki` parses any page carrying the Education template —
but sink-written support pages (`Education:Index`, synthetic series
hubs) carry it with `status=index`, so `skipped_non_lesson` was 0 and
"education index" polluted the upcoming queue and the index itself.
Door now skips `status=index` rows (lands on next door restart);
`lessons-due.py` filters client-side so the job is correct against
both door builds. Corpus: 125 real lessons.

**New — daily `Education:Index` refresh.** The index previously only
regenerated on manual `wiki-lesson-migrate.py` runs — stale between
runs now that `do_lesson` dual-writes daily. `lessons-due.py` gained
`index_wikitext(rows)` (same level-grouped shape) and writes
`Education:Index` whenever `--dest` includes wiki + `source=wiki`;
`--no-index` / `LESSON_INDEX=0` opts out; failure reported
independently. Provenance header on both writers updated.

## Verification

- `python3 -m unittest tests.test_lessons_due
  tests.board.test_publication tests.board.test_board_api_mutations
  tests.test_education_report` → 104 tests OK (+4 new: actor=`chaba`,
  status=index door skip, client filter, index render x2).
- `render-jobs.py --check` → 93 jobs OK; `ssot-validate-all.mjs` →
  0 errors.
- Live: door probes + due/index writes above; anon 404 check.

## Docs updated

- `docs/ssot/jobs/education/2026-11-07-wiki-education-due-index.yml`
  (new trail doc — bugs, fixes, verification, remaining gates)
- `…/2026-11-06-wiki-education-read-door.yml` — verify items marked
  done with live evidence
- `…/2026-11-06-wiki-member-knowledge-surface.yml` — step 5 DONE,
  step 6 mechanics noted (301 map derivable from door rows)
- `ssot.jobs.yml` `chaba-lessons-due` — name/note cover index refresh

## Remaining gates (not this dispatch's scope)

- **Step 6 (WP admin/Tony):** lesson CPT read-only + permalink 301s to
  `Education:<title>` — then `--dest wp` can drop and `EDU_SOURCE=wiki`
  becomes the report default (still gated per its manifest note).
- **Door restart on idc03** ships the `status=index` corpus filter
  (cosmetic until then — lessons-due compensates client-side) and the
  `do_wiki_page` session fix is already live.
- **Door unresponsive on `/comment` + `/card`** at session end (~12:10
  +07): `/publish` answered instantly but card-write paths hung >30s
  — likely the same broken served-checkout topology noted in the plan
  doc anomalies (board-api runs detached from the exec checkout;
  kanban-commit on idc03's served checkout is failure-streaked).
  Progress comment posted early in session; final results comment
  retried — if it didn't land, this file is the record. Worth an ops
  look alongside the ops-kanban-commit-guard card.

## Files changed

`scripts/lessons-due.py` (actor, index refresh, status=index filter,
`--no-index`), `scripts/board/board-api.py` (corpus filter),
`scripts/wiki-lesson-migrate.py` (index provenance),
`tests/test_lessons_due.py`, `tests/board/test_publication.py`,
`docs/ssot/infrastructure/ssot.jobs.yml`, the two education job docs,
+ new `2026-11-07-wiki-education-due-index.yml`.
