# Dispatch outcome — wiki education surface, step 4 (read door + retarget)

Card: `wiki-member-knowledge-surface-migrate-wp-3a1cf2` (5th dispatch
today; earlier runs shipped plan, 2a/2b tooling, live migration).
Branch `dispatch/20261106-201214-idea-2026-11-06-tony-chat-migr`,
commit `02af324` — 11 files, +884/-74.

## Shipped (repo-side, behind the existing merge+restart gate)

- **`scripts/board/board-api.py` — `/lesson` gains `source=wiki`**:
  `op=list|get` walk the Lockdown-protected `Education:` namespace via
  the bot login (siteinfo ns-id resolve -> allpages -> revision batches
  of 50), parse the `แม่แบบ:Education` call into the same row shape WP
  returns, and mint **identical `lesson-<md5(topic)>` slugs** — op=get
  by slug, audit keys, and `lesson-thai-exceptions.yml` all survive
  cutover. Rows add `wiki_title` + `url`; non-lesson pages
  (`Education:Index`, `:Due`, hubs) are skipped and counted. Get accepts
  `slug` | `wiki_title` | `topic`. WP responses now carry `source:"wp"`.
- **Bug found live + fixed**: `op=list` never paginated — the live door
  returned `count: 100` against a 124-lesson corpus, so the daily
  education-report was silently auditing ~24 lessons short. Now pages
  to 500 (same bound as `do_lesson_topics`).
- **`scripts/lessons-due.py` retargeted**: `--source wiki` (new default)
  reads via the door (no more WP creds needed for the read); `--dest
  both` (new default) writes `Education:Due` through `/wiki/page` AND
  keeps updating the WP `education-due` page (post 354) during the
  transition. `LESSON_SOURCE=wp --dest wp` is the pre-migration
  fallback; per-dest failures report independently.
- **`scripts/education-report.py`**: `--source wp|wiki` (`EDU_SOURCE`,
  default wp until cutover) — the audit/drift regexes are
  format-agnostic so wikitext bodies work.
- **Stale-door guard (both tools)**: a door that predates the wiki read
  path ignores `source` and answers WP rows — verified live today.
  Both tools check `source:"wiki"` is echoed and fail loudly instead of
  auditing the WP corpus under a wiki label.
- **Manifest**: `chaba-lessons-due` name/note updated + idc03 units
  re-rendered (Description only); `chaba-education-report` note
  documents the `EDU_SOURCE=wiki` cutover flip.
- **Docs**: plan doc step 4 marked done;
  `docs/ssot/jobs/education/2026-11-06-wiki-education-read-door.yml`
  is the phase trail (design notes, activation gate, verify steps).

## Verification

- `python3 -m unittest tests.board.test_publication
  tests.test_lessons_due tests.test_education_report
  tests.board.test_board_api_mutations` → **102 tests OK**
  (new: 4 wiki-read tests incl. slug parity + ns-gate; 8 lessons-due
  tests incl. stale-door + payload shape; 1 report source test).
- `render-jobs.py --check` → 92 jobs OK; ssot-validate on touched
  YAMLs → valid.
- Live (read-only): `/lesson {op:list, source:wiki}` against the
  deployed door returns 100 WP rows with no `source` key — confirming
  both the stale-door guard's necessity and the pre-existing
  100-of-124 truncation.

## Card comment could not be posted

`/comment` on this card errors `no card ...` — the running door (exec
checkout `~/CascadeProjects/chaba`) doesn't have the card file and it
isn't in `origin/master` either. Consistent with the phase-3 anomaly:
the served checkout is diverged (kanban-commit pull failure-streak),
so cards written there never reach origin or the exec checkout. The
same divergence blocks the door from seeing this card. Needs the
ops-kanban-commit-guard fix; my durable trail is in the committed
docs above.

## Activation gate (unchanged, one restart covers two dispatches)

1. Merge this branch + dispatch/20261106-193421 → idc03 pull →
   restart board-api. Activates: `/lesson source=wiki`, the
   `do_wiki_page` session fix (currently 502s), and paginated op=list.
2. Post-restart verify: `op=list source=wiki` → `source:'wiki'`,
   ~124 lessons; `lessons-due.py --dry-run` renders `Education:Due`
   from the live corpus; `lessons-due.py` writes both dests.
3. Step 6 (WP admin): lesson CPT read-only + 301s; then `--dest wp`
   and `EDU_SOURCE=wiki` flip become final.
