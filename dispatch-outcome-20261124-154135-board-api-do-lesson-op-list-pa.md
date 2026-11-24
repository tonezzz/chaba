# Dispatch outcome — door-read-ops-lesson-op-list-get-educati-6cfed7

Card: `door-read-ops-lesson-op-list-get-educati-6cfed7` (OPS-0821)
Branch: `dispatch/20261124-154135-board-api-do-lesson-op-list-pa`
Commit: `6e7306e85c` — board-api: /lesson op=list paging + op=get topic field (OPS-0821)

## What I found

The card's core work was already shipped:

- `6a452479df` (2026-10-24, same ref OPS-0821) added `/lesson`
  `op=list`/`op=get` for the WP source — exactly this card's spec.
- `02af324ce7` (2026-11-06, OPS-1046) added `source=wiki` (Education:
  namespace) and `source=mddb` (chaba-lessons mirror) read paths, plus a
  `do_lesson_topics` store-aware read.

The card sat in `backlog` anyway — a stale re-queue. Live verification
against `https://idc03.taila0626a.ts.net:10000` confirmed the deployed
door already answers the spec: `op=list` returned 220 wiki lessons with
`{slug, topic, level, modified, next_review, status}` (+`no_th`,
`wiki_title`, `url`), `op=get` returned content+meta, `op=topics`
returned 220 topics.

## What I changed (scripts/board/board-api.py only)

Two literal-spec gaps closed, both backwards-compatible:

1. **op=list pagination** — new `_lesson_page()` helper applies optional
   `limit`/`offset` body params to all three sources (wp/wiki/mddb),
   mirroring the GET /cards convention: `limit` capped at
   `LESSON_LIST_MAX=500`, response gains `total`/`offset`/`truncated`,
   `count` = returned page size. No params → full list, so
   lessons-due.py, education-report.py, lesson-mddb-backfill.py and
   do_lesson_topics are unaffected (they never pass limit/offset).
2. **op=get `topic` field** — spec shape is `{slug, topic, content,
   meta}`; get previously returned `title` but no top-level `topic`.
   Now returns `topic` on all sources: wp = meta.topic (fallback: title
   minus `Education — ` prefix), mddb = meta.topic, wiki = row.topic.
   `title`/`content`/`meta`/`modified` keys unchanged.

Write path untouched: `do_lesson` upsert/touch/delete, `_lesson_wiki_*`
writers, `do_lesson_topics` — zero changes.

## Verification

- `python3 scripts/board/board-api.py --selftest` → `selftest ok`
  (added ~80 lines covering op=list paging + op=get topic for all three
  sources, incl. bad-param degradation and wiki index-page skipping).
- Live door (pre-change code): op=list 220 lessons, op=get full
  content+meta, op=topics 220 — consumer contract confirmed.
- Consumers audited: lessons-due.py / education-report.py /
  lesson-mddb-backfill.py read `lessons`/`count`/`content`/`meta`/
  `title` — all preserved; lesson-add.py is a write-only thin client.
- Takes effect on merge + board-api service restart on idc03 (served
  checkout pulls via kanban-commit/git-safe-pull).

## Lessons

- Stale backlog cards re-dispatch: check `git log -S <ref>` for the card's
  `ref:` (OPS-xxxx) before implementing — OPS-0821 shipped the same day
  the card was filed.
- board-api `_selftest` finally-block references `real_tg_url` etc.
  defined mid-try — an early assert failure masks the real error with
  UnboundLocalError. Cosmetic, pre-existing.
- `truncated` semantics = `offset + len(page) < total` (same as
  GET /cards): the LAST page reports truncated:false — test the
  first page for true, not the last.
