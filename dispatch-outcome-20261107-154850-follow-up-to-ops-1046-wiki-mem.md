# Dispatch outcome — wiki-education-write-cutover (follow-up to OPS-1046)

Card: `wiki-education-write-cutover-make-wiki-t-7f2e7d` · runner: idc02 · 2026-11-07

## What changed

- `scripts/board/board-api.py` — `WIKI_EDUCATION_WRITE` gains a `wiki`
  mode (flag semantics now `off`=WP only, `dual`=WP+wiki, `wiki`=wiki-
  primary, rollback=set `dual`):
  - `do_lesson` wiki-primary branch (`_lesson_wiki_primary`): writes via
    `WikiLessonSink` only — **zero `/wp/v2/lesson` calls**. Upsert is by
    `wiki_title` = `pub.lesson_wiki_title(topic)` (the slug-equivalent —
    a re-asked topic resolves to the same page). On re-file,
    `learned_at`/`next_review`/`status` are preserved from the existing
    page's template params; explicit `next_review` wins; `no_th` is
    carried when a Thai-free re-file meets a prior exemption. Result
    carries `wiki_title`, `url`, `action`, `store:"wiki"` — **no
    `post_id`**. A wiki failure raises (502) since there's no second
    store.
  - `op=delete` in wiki mode targets the Education: page (the live
    store), not the WP archive; slug resolves via the same
    `lesson-<md5>` mint. `op=touch` stays WP-scoped archive maintenance.
  - Read default follows the flag: `op=list|get` with no `source`
    resolves `wiki` when WRITE=wiki (explicit `source=wp` still reads
    the archive). Consumers without a source — embed-lane,
    bge-lessons-shadow — retarget automatically.
  - `op=topics` gained a `source` param + wiki listing (same default
    rule).
  - **Bugfix** `url_of()`: emitted `{host}/wiki/<t>` which 404s live —
    wiki.h3 has no `$wgArticlePath`. Now `/index.php?title=<t>`
    (canonical form, verified live 2026-11-07). Affected read-path `url`
    fields and lessons-due hrefs.
  - `_wiki_lesson_sink()` shared ctor honors `WIKI_EDUCATION_TEMPLATE`/
    `WIKI_EDUCATION_PREFIX` overrides (previously only `_pub_sinks` did).
- `scripts/board/publication.py` — `WikiLessonSink` merges sparse meta
  from the existing page before edit (`_prepare_event` hook on
  `MediaWikiSink.publish`): `topic/level/lesson_source/learned_at/
  next_review/status` fill when unset; `no_th` inherits only when the
  new body is Thai-free (Thai landing drops the exemption — same as WP
  semantics). Door path populates everything so the extra fetch is
  skipped there; this is the safety net for direct `/publish` + migrate
  callers.
- `tests/board/test_publication.py` — 18 new tests: sink merge (sparse
  inherit, explicit override, no_th keep/drop, no-fetch fast path,
  missing page), wiki-primary door (no WP calls, wiki-shaped result,
  re-file state preservation, next_review override, incomplete-creds
  502, default read/topics follow flag, explicit wp archive read,
  wiki-mode delete targets the page).
- `scripts/wiki-lesson-redirect-map.py` — NEW: regenerates the redirect
  fragment from `/lesson op=list source=wiki` (slug→wiki_title is not
  derivable from `lesson-<md5>` alone).
- `stacks/idc02/boards-lesson-redirects.caddy` — NEW generated fragment:
  131 lesson mappings + archive fallback. `path_regexp` captures the
  slug under both `/wp/lesson/<slug>` and `/wp/index.php/lesson/<slug>`
  (immune to ordering vs the site's clean-URL rewrite); `map` → 301 to
  `wiki.h3/index.php?title=<wiki_title>`; unmapped slugs →
  `Education:Index`; bare `/wp/lesson[/]` → `Education:Index`.
  Validated via `caddy validate` + `caddy adapt` (docker caddy:2).
- `docs/ssot/jobs/education/2026-11-07-wiki-education-write-cutover.yml`
  — SSOT trail: flag semantics, ship list, redirect install steps,
  verify-by-surface checklist, post-cutover followups.
- `docs/ssot/apps/ssot.wp-boards.yml` — `lesson_cpt_cutover` note.

## Findings

- `do_lesson` is the **only** writer of `/wp/v2/lesson` — every producer
  goes through the door (lesson-add.py, ada lesson-miner,
  wiki-lesson-migrate, `/publish kind=lesson`). No other writer needs
  changing; after the flip the CPT is a frozen archive by construction.
- Redirect choice: **edge-level** is the only repo-manageable layer —
  boards.surf-thailand.com is CF → idc02 caddy-edge → Plesk origin;
  WP docroot has no FTP, the wiki FTP user is jailed to MediaWiki, and
  a mu-plugin needs Tony/WP-admin. Edge is also durable against WP
  plugin updates.
- 3 pre-existing/unrelated test failures in the full suite (missing
  `pytest` for `test_ada_job_envelope`, env-dependent lane-model
  assertion `litellm/gemini-2.5-flash` vs expected `or-claude-fable-5.1`
  in two runner-agent tests).

## Result

All 92 board tests pass (`tests/board/test_publication` +
`test_board_api_mutations`). Code + redirect fragment are in the
worktree on this branch — **no commit to default branch, no push, no
live flag flip, no deploy** (flag is read per request so the live flip
needs no restart, but the code must be merged + pulled to the served
checkout first; board-api restart picks it up).

## How to verify (post-merge, on idc03)

1. Flip `WIKI_EDUCATION_WRITE=dual` → `wiki` in
   `~/.config/secrets/wiki-h3-gizmo.env`.
2. `POST /lesson` new topic → result has `wiki_title` + `store:"wiki"`,
   **no `post_id`**; `Education:<title>` page exists; WP lesson count
   unchanged.
3. Re-file the same topic → **same** wiki page updated, `learned_at` +
   `next_review` + `status` preserved; explicit `next_review` advances.
4. `lessons-due.py` still renders (reads `source=wiki` already; daily
   timer unaffected).
5. Anon denied: unauthenticated `/index.php?title=Education:<t>` →
   Lockdown/denied page.
6. Redirects (after ops import step — add
   `import .../boards-lesson-redirects.caddy` inside the
   boards.surf-thailand.com site block in `~/.config/caddy/Caddyfile`
   on idc02 + `caddy reload`):
   `curl -sI https://boards.surf-thailand.com/wp/lesson/<slug>/` →
   `301` → `wiki.h3/index.php?title=Education:<t>`.
7. Rollback check: flag back to `dual` → next write creates WP post +
   wiki page as before.
