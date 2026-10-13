# Dispatch outcome — ada-trip-calendar-pages (2026-10-13)

## What changed (committed on this worktree branch, not pushed)

- **`scripts/ada/trip-calendar.py`** — the generator. Merges
  CalendarService.list_events (ada-pi `backend.calendar_providers`,
  lane-scoped registry file) with LINE `conv_journal` archive context
  (`journal-<day>.jsonl` under `LINE_MEDIA_ARCHIVE_DIR`). Writes the
  cms-page-standard family: rollup `trip-<slug>` (lede + mermaid gantt +
  day table → leaf links), daily leaves `trip-<slug>-<YYYY-MM-DD>`
  (time|event|detail schedule + journal notes), and `trip-<slug>-qc`
  (coverage/staleness/source self-check). Regenerates `reports-index`
  after writes. Args: `--slug --from --to --lane tony|kk|kk-dev
  --public --title --keywords --chat --no-journal --dry-run --json`.
  Span inferred from a matching calendar event when dates are omitted;
  re-execs under `ada-pi/.venv` when ambient python lacks httpx.
- **`integrations/ada-pi/`** — the Ada-side drop-in, staged (this
  session may not write outside the worktree):
  `backend/tools.d/trip_calendar.py` (shells the generator, lane bound
  by `ADA_CMS_COLLECTION`, `public='yes'` requires `confirmed='yes'`),
  `manifest.trip_calendar.yml` + `tool_guide.trip_calendar.yml`
  snippets, README install steps.
- **`docs/ssot/apps/ssot.apps.ada-persons.yml`** — `trip_calendar`
  added to `persons.kk.tools.include`, `kk-cms-only`, `kk-parity`.
  Drift fix: `kk-parity` also gained `page_snapshot` + `conv_journal`
  (it claimed parity with persons.kk but was missing both).
- **`docs/ssot/jobs/ada/2026-10-13-trip-calendar-pages.yml`** — trail:
  design, lane map, meta contract, verify evidence, gaps.

## Verified

- `--dry-run` reviewed (synthetic events + real kk-dev data).
- Live run: `--slug capetown --from 2026-10-12 --to 2026-10-13
  --keywords "เคปทาวน์,ทริป,africa" --lane kk-dev` → rollup + 2 leaves +
  qc in `ada-cms-pages-kk-dev`; correct `report_role`/`parent` meta;
  real Thai journal notes on the leaf; `reports-index` regenerated with
  all four rows.
- Mermaid gantt renders in the real CMS app — page copied to
  `ada-cms-pages/trip-capetown-devcheck`, screenshotted via playlived at
  `idc03.taila0626a.ts.net/cms/#/trip-capetown-devcheck`, then deleted.
- `--public` on kk-dev warns and does NOT flag (no publish tenant);
  inference failure exits rc=2 with a clear message.

## Not done / follow-ups

- Ada tool is staged, NOT deployed — needs an ada-pi session to copy
  the module + manifest/tool_guide snippets, run tool-lint/pytest,
  redeploy. (Also found: `conv_journal` has no manifest entry in
  ada-pi b776e81 — unreachable as a tool; add both.)
- kk's Google calendar is empty → trip pages currently carry journal
  context but 0 events. tony lane calendar_read is currently broken by
  a 404 on one configured calendar (the literal
  `${GOOGLE_CALENDAR_JARVIS_CALENDAR_NAME}` registry entry) which fails
  the whole aggregate read — a real trip demo should run on kk once
  her calendar has events, or after the tony registry is fixed.
- LINE/TG share path: tool returns `public_url`
  (`surf-thailand.com/<tenant>/`); `page_snapshot` covers image-send.
