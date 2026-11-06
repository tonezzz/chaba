# Dispatch outcome — wiki member knowledge surface, phase 2b

Card: `wiki-member-knowledge-surface-migrate-wp-3a1cf2` (third dispatch
on it today — earlier runs produced the plan doc and phase-2a lesson
tooling). Branch `dispatch/20261106-184016-idea-2026-11-06-tony-chat-migr`,
commit `b5a2075`.

## Verified live (read-only, no prod writes)

- **Namespaces registered**: `Education:`+talk = 3004/3005 and
  `Reports:`+talk = 3006/3007 exist on wiki.h3 (siteinfo) — the
  Tony/Plesk LocalSettings step from the cutover checklist has landed,
  matching the ids in the card snippet.
- **Templates still missing**: `แม่แบบ:Education`, `แม่แบบ:Report` absent
  (`แม่แบบ:NewsReport` exists, pageid 12).
- **Lockdown works** via the `inhouse` group: anon content read on
  `Infrastructure:Hosts/idc03` → `accessdenied`. But Lockdown for the NEW
  namespaces is **unverifiable while empty** — needs a first-write probe.
- **Deployed door is stale**: `/publish op=sinks` on idc03 reports 9
  sinks (no `wiki-education`) — the running board-api predates even
  phase 2a; it needs a restart after merge before any `--apply`.

## Shipped (repo-side, all behind existing gates)

- `scripts/board/publication.py`: `report_wiki_title()` +
  `WikiReportSink` — `kind=report`, private surface, `Reports:` prefix,
  template `แม่แบบ:Report`, opt-in only (default report routing
  unchanged, so dossier notes never leak to the wiki).
- `scripts/board/board-api.py`:
  - `POST /wiki/page` (`do_wiki_page`) — guarded support-page write:
    allowlisted templates + `Education:`/`Reports:` titles only, and
    prefix titles verify the namespace is registered via siteinfo
    before writing (prevents main-space litter).
  - `do_report mode=wp-list|wp-get` — door read for the member-facing
    WP report CPT (`report_type`/`period`/`source_key` meta).
  - `wiki-reports` registered in `_pub_sinks`; `_wiki_login` +
    `_wiki_namespaces` helpers.
- `scripts/wiki-support-pages.py` — declares both template pages
  in-repo; `--apply` writes them via `/wiki/page`.
- `scripts/wiki-report-migrate.py` — door read → `Reports:<type>/<period>`
  living pages + `Reports:Index` → `/publish sinks=['wiki-reports']`;
  mirror of the lesson migrate tool.
- Docs: new trail `docs/ssot/jobs/education/2026-11-06-wiki-reports-surface-tooling.yml`;
  plan doc updated with verified namespace state, phase-2b line, and the
  revised sequence.

## Verification

- `python3 -m unittest tests.board.test_publication` → **54 OK**
  (+ReportWikiTitleTest, WikiReportSinkTest, 5 wiring tests incl.
  /wiki/page refuse-paths and the namespace gate).
- `python3 -m unittest tests.board.test_board_api_mutations` → **21 OK**.
- Both scripts compile; `wiki-support-pages.py` dry-run prints the two
  templates.

## Remaining gates (documented in the plan doc + card comms)

1. Merge this branch; **restart board-api on idc03** (repo-sync pulls
   the code but the process must restart to register the new sinks).
2. `wiki-support-pages.py --apply` — creates both templates.
3. One-page probe `--apply` → anon `accessdenied` check → then the
   full 124-lesson + report migration.
4. `WIKI_EDUCATION_WRITE=dual` env flag on idc03; then WP CPT read-only
   + 301s and lessons-due/education-report retarget.
