# Dispatch outcome — wiki education surface, phase 2a tooling

Card: `wiki-member-knowledge-surface-migrate-wp-3a1cf2`
Runner: idc02 · 2026-11-06 · branch `dispatch/20261106-181239-idea-2026-11-06-tony-chat-migr`

## Context (from card history)

Phase 1 (earlier dispatch) verified the wiki already exists
(wiki.h3.gizmo-thailand.com, MW 1.46.2, Lockdown-enforced protected
namespaces, MediaWikiSink + wiki doors live in board-api) and wrote the
structure plan `docs/ssot/jobs/education/2026-11-06-wiki-member-knowledge-surface.yml`.
Tony answered: engine=mediawiki, visibility=inhouse-after-sso,
scope=proceed. This dispatch = phase 2a: build the tooling, **no live
wiki writes** (the `Education:` namespace still requires Tony's
LocalSettings/Plesk step — verified snippet is on the card, ns ids
3004-3007).

This worktree merged the earlier plan branch first so the plan doc and
the ssot.mediawiki-news drift repairs are part of this branch's base
(identical-commit merge is conflict-free when both land).

## What changed

- `scripts/board/publication.py`
  - `html_to_wikitext()` — stdlib HTMLParser converter for lesson-body
    HTML (headings, p/br/hr, nested ul/ol, links, bold/italic, code/pre,
    blockquote; script/style dropped, unknown tags flatten).
  - `lesson_wiki_title()` — readable `Education:<Topic>` titles
    (`ada-nest-map` → `Education:Ada-Nest-Map`); md5 slugs never leak.
  - `WikiLessonSink(MediaWikiSink)` — `kinds=('lesson',)`,
    `surface='private'` (protected ns = staff-only at cutover),
    `namespace_prefix='Education:'` (env `WIKI_EDUCATION_PREFIX`),
    template `แม่แบบ:Education` (env `WIKI_EDUCATION_TEMPLATE`).
    `meta.format='wikitext'` passes the body verbatim; anything else is
    treated as lesson HTML and converted. Title derives from
    `meta.topic` when `meta.wiki_title` is absent.
  - `MediaWikiSink.edit_label` parameterizes the edit summary.
- `scripts/board/board-api.py`
  - `_pub_sinks` registers `wiki-education` when `wiki-h3-gizmo.env`
    creds exist — `/publish op=sinks` reports it; explicit
    `sinks=["wiki-education"]` works today.
  - `_lesson_wiki_write()` + `do_lesson` hook — dual-write behind
    `WIKI_EDUCATION_WRITE=dual` in `wiki-h3-gizmo.env`. **Ships OFF.** A
    wiki failure reports `result["wiki"]={status:failed,...}` and never
    fails the WP write.
- `scripts/wiki-lesson-migrate.py` (new) — door-read export
  (`/lesson op=topics` + `op=get`, no WP creds on the runner) →
  wikitext → `--apply` via `/publish sinks=["wiki-education"]`
  (deterministic idempotency keys = reruns dedupe). Emits a generated
  `Education:Index` and series hubs (`ada-nest-map` becomes
  `Education:Ada-Nest` + appended Series link list; `SERIES` extensible).
- `tests/board/test_publication.py` — 13 new tests: converter (4),
  title helper, sink publish/metadata/passthrough/derived-title/gates
  (4), wiring: sink registration + dual-write flag (2).

## Result / verification

- `python3 -m unittest tests.board.test_publication` → **43 tests OK**
- `python3 -m unittest tests.board.test_board_api_mutations` → **21 tests OK**
- `scripts/wiki-lesson-migrate.py --limit 4` against the **live door**
  (read-only): fetched real lessons, produced `Education:*` titles +
  index; converted wikitext is clean (Thai section, lists, `<pre>`,
  bold all map correctly).
- `scripts/ssot-validate-all.mjs` on the touched SSOT docs → valid.
- No writes to WP or the wiki were made; door calls were read-only.

## Trail

- `docs/ssot/jobs/education/2026-11-06-wiki-education-sink-tooling.yml` —
  what shipped, verification, cutover checklist.
- Plan doc `implementation_sequence` updated: step 2 marked done repo-side.

## Remaining gate (Tony-only, unchanged)

1. LocalSettings snippet (card comm 18:13) → registers `Education:`+talk
   (3004/3005) and `Reports:`+talk (3006/3007) with Lockdown rules.
2. Create `แม่แบบ:Education` on the wiki (params: topic, level, source,
   learned_at, next_review, status, updated, no_th, event_id).
3. `WIKI_EDUCATION_WRITE=dual` in `wiki-h3-gizmo.env` on idc03.
4. `wiki-lesson-migrate.py --apply` (124 pages + index + hubs).
5. Verify-by-surface: anon accessdenied on `Education:`, authed read ok,
   one live `/lesson` write lands on the wiki.
6. WP lesson CPT → read-only + 301s; lessons-due/education-report
   retarget (Cargo query or API list).

Follow-ups noted in the job doc: WP report-CPT has no door read (needs a
door op or idc03-side WP access; ~5 pages); `Reports:` writer is a small
future sink variant.
