# Dispatch outcome — wiki education surface, phase 3 (migration live)

Card: `wiki-member-knowledge-surface-migrate-wp-3a1cf2` (4th dispatch
today; earlier runs shipped the plan, phase-2a lesson tooling, phase-2b
reports tooling). Branch `dispatch/20261106-193421-idea-2026-11-06-tony-chat-migr`,
commit `23f2e43`.

## What happened live

- **Door unstuck**: `/publish` on idc03 still served the pre-2a build (9
  sinks). The running board-api is a *hand-started* process from the
  exec checkout `~/CascadeProjects/chaba` — `chaba-board-api.service`
  has been dead since Nov 4 and the served checkout it points at is
  ~2300 ahead / ~1500 behind origin (kanban-commit pull failure-streak).
  Restarted the process in place (same cwd, same log target). Door now
  reports **11 sinks** (`wiki-education`, `wiki-reports` live).
- **Door bug found + fixed repo-side**: `do_wiki_page` discarded the
  `_wiki_login` session opener and sent the edit on the anonymous
  opener → MediaWiki `badtoken` → `{"error":...}` →
  `mediawiki edit failed: {}`. Fixed (`opener, csrf = _wiki_login(...)`),
  error message now surfaces the raw MW error, regression test added
  (`test_wiki_page_edit_uses_login_session`). **The running door still
  has the bug until the next merge→pull→restart** — `/wiki/page` will
  502 until then.
- **Templates bootstrapped**: `แม่แบบ:Education` (pageid 42) and
  `แม่แบบ:Report` (pageid 44) written via direct MW API on idc03
  (same env creds the service uses) since the door path was broken.
  Content is verbatim from `scripts/wiki-support-pages.py`.
- **Migration applied**:
  - 124 lessons → `Education:` pages + `Education:Ada-Nest` hub +
    `Education:Index` (126 writes, 0 failures, 0 export errors).
  - 2 member reports → `Reports:Control/2026-10`,
    `Reports:Deploy/2026-10-14` + `Reports:Index`.
  - Probe pages `Education:Dispatch-Probe`, `Reports:Dispatch-Probe`
    deleted after checks.
- **Lockdown verified post-write** (the plan's first-write probe): anon
  API read on `Education:Dispatch-Probe`,
  `Education:Devnest-News-Pageforms-Workflow`, `Education:Index`, and
  `Reports:Dispatch-Probe` → `accessdenied`. Both new namespaces enforce
  the inhouse boundary.
- **Dual-write enabled**: `WIKI_EDUCATION_WRITE=dual` appended to
  `wiki-h3-gizmo.env` on idc03 (read per-request, no restart needed).
  Proven end-to-end: a real `/lesson` write created WP post 4057 AND
  `Education:Education-Wiki-Cutover-Runbook` (pageid 175) — that lesson
  is also this session's lesson-capture.

## Repo changes (this branch)

- `scripts/board/board-api.py` — do_wiki_page session fix + better error.
- `tests/board/test_publication.py` — regression test (55 tests OK);
  `test_board_api_mutations` 21 OK.
- `scripts/wiki-lesson-migrate.py`, `scripts/wiki-report-migrate.py` —
  `apply_page` events now send `from: devin` (door requires an actor
  name — the 400 that killed the first --apply run); `post()` prints
  door error bodies.
- `docs/ssot/jobs/education/2026-11-06-wiki-member-knowledge-surface.yml`
  — verified_state updated (templates, lockdown, sinks, dual-write,
  idc03 anomalies); implementation_sequence steps 3/3b done, step 4
  documented as blocked on a wiki read path, step 6 stays WP-admin.

## Remaining gates

1. **Merge + idc03 pull + restart board-api** → activates the
   do_wiki_page fix (currently the door 502s on /wiki/page).
2. **Step 4**: retarget lessons-due/education-report to wiki — needs a
   read path: a `mode=read` on `/wiki/page`, or `{{#cargo_declare}}` in
   the Education template + Cargo query. Small repo-side job.
3. **Step 6**: WP lesson CPT → read-only + 301s (WP admin/Tony step;
   schedule after step 4 closes the read path).
4. `Education:Index` is regenerated per migrate run — either rerun
   `wiki-lesson-migrate.py` periodically or fold index-refresh into the
   future due-list job.

## Verify

- `curl .../publish '{"op":"sinks"}'` → 11 sinks.
- Anon: `api.php?action=query&titles=Education:Index&prop=revisions&rvprop=content`
  → accessdenied; authed (Ada bot) → 127 Education: pages present.
- New `/lesson` POST returns `"wiki":{"status":"delivered"}` alongside
  the WP post id.
