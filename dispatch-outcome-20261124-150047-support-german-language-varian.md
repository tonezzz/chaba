# Dispatch outcome — support-german-language-variants-on-cms-69ef23

Card: Support German language variants on CMS pages (user wanted a `de`
variant of `translate-probe`; only EN/TH appeared supported).

## What I found

The store never restricted language. MDDB keys docs by
`(collection, key, lang)` and accepts any code — verified live by writing
and reading `ada-cms-pages/translate-probe` `lang=de`. The EN/TH wall was
in two other places:

1. **chaba readers special-cased `th`.** `scripts/lib/cms_index.py`
   dropped every `lang=="th"` doc unconditionally (a `de` doc would have
   produced a duplicate reports-index row, and th-only keys were
   invisible). `apps/cms-render/server.py` `index_rows` had the same
   th-only skip, so a `de` doc listed before `en` could win the index
   row's title.
2. **ada-voice tool surface** (`cms_publish_page` / `cms_edit` /
   `cms_read`, `backend/realtime_provider.py`) — different repo; the
   `lang` arg still presents en/th only. Follow-up card filed:
   `open-ada-cms-tool-lang-arg-beyond-en-th-37f8a0` (ADA-0030, repo
   ada-voice, executor devin).

## What changed (this worktree, branch dispatch/20261124-150047-…)

- `scripts/lib/cms_index.py` — `index_rows` now emits one row per key:
  `en` wins when an en sibling exists, otherwise the first-seen variant
  emits. Any lang (de, ja, …) dedupes like th did; variant-only keys
  surface instead of vanishing.
- `apps/cms-render/server.py` — same generalization in `index_rows`
  (any non-en yields to an en sibling regardless of listing order).
  `resolve()`/`?lang=` and the template lang switcher were already
  generic — verified live.
- `scripts/board/board-api.py` — `/report` create mode accepts a `lang`
  body param (was hardcoded `"en"`); sets both doc lang and `meta.lang`.
  `note` mode already passed lang through.
- Tests: `tests/camwall/test_cam_wall_cms.py` (IndexLibTest),
  `tests/ada/test_cms_render.py` (IndexRowsTests),
  `tests/board/test_board_api_mutations.py` (ReportDoorTest) — new cases
  cover de-before-en ordering, de-only/th-only keys, and `/report`
  `lang=de` payload shape.
- Trail doc: `docs/ssot/jobs/ada/2026-11-24-cms-german-language-variants.yml`.

## Live verification (no deploy needed — store + renderer already generic)

- Created `ada-cms-pages/translate-probe` `lang=de` via MDDB `/v1/add`
  with the German sentence Tony dictated to Ada on 2026-10-05 (source:
  `docs/ada-memory/inbox/personal/translate-probe-content.md`).
- `http://100.102.134.91:8010/p/translate-probe?lang=de` renders the
  German page; switcher shows en/th/de; default serves EN.
- Ran `regen_reports_index` from the worktree against live MDDB:
  translate-probe = exactly 1 index row, 0 duplicate slugs in 425 rows.

## How to verify

- `python3 -m pytest tests/camwall/test_cam_wall_cms.py tests/board/test_board_api_mutations.py -x -q`
- cms-render suite needs its venv (`apps/cms-render/requirements.txt` +
  `httpx2` for TestClient): `/tmp/cmsrender-venv/bin/python -m unittest tests.ada.test_cms_render`
- Live: `curl 'http://100.102.134.91:8010/p/translate-probe?lang=de'`
- Board-api: `POST /report {"mode":"create","slug":"x","lang":"de","title":"…","content_md":"…"}`

## Notes / caveats

- Until ADA-0030 lands, Ada by voice still can't self-serve `lang=de`
  through `cms_publish_page`; agents can write variants via MDDB
  `/v1/add` or board-api `/report`.
- reports-index regens on hosts still running pre-merge code will emit a
  transient duplicate row for any key gaining a non-th variant; it
  self-heals on the first regen after this merges + chaba-repo-sync.
- th-only index rows now surface where they were previously dropped
  (both live th-only keys are superseded, so no visible change today).

lessons:
- "Only en/th supported" was never the MDDB store — verify the store layer first; the wall was chaba reader special-casing plus the ada-voice tool schema in a different repo.
- cms_index.index_rows dropped ALL th docs (mirrors AND th-only keys); prefer-en dedup fixed both the de-dup hole and th-only invisibility.
- cms-render FakeMDDB sorts docs by (coll,key,lang) so de precedes en — good accidental coverage for listing-order bugs in lang dedup.
- board-api /report create hardcoded lang="en" while note mode already took lang — create was the gap, not the door.
