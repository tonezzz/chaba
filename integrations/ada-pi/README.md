# ada-pi drop-ins

Staged files for the **ada-pi repo** (`tonezzz/ada-pi`), produced by
chaba dispatches. Four drops live here:

1. `trip_calendar` — card `ada-trip-calendar-pages` (2026-10-13)
2. `doc_read` + line_relay file ingest — card `line-file-doc-ingest`
   (2026-10-13)
3. calendar create dedup — card `calendar-write-idempotency` (2026-10-13)
4. `place_report` — card `maps-url-to-cms-line-maps-link-resolved-c418f8`
   (2026-10-13) — **already deployed** (ada-pi `074c7a8`+`e24b14d`); this
   drop is the repo-of-record copy

---

## Drop 1 — trip_calendar tool

The generator half (`scripts/ada/trip-calendar.py`) lives in THIS repo;
these files are the Ada-side surface.

### Install (ada-pi worktree)

1. `cp integrations/ada-pi/backend/tools.d/trip_calendar.py
   <ada-pi>/backend/tools.d/trip_calendar.py`
2. Merge `backend/tools.d/manifest.trip_calendar.yml`'s `trip_calendar:`
   block into `<ada-pi>/backend/tools.d/manifest.yml` under `tools:`.
   (Note: `conv_journal` is also missing a manifest entry on
   b776e81-era checkouts — add both while there.)
3. Append `backend/tool_guide.trip_calendar.yml` to
   `<ada-pi>/backend/tool_guide.yml`.
4. Tool profiles already updated in this repo —
   `docs/ssot/apps/ssot.apps.ada-persons.yml` adds `trip_calendar` to
   `persons.kk.tools.include`, `bench_profiles.kk-cms-only` and
   `kk-parity` (parity also gained the missing `page_snapshot` +
   `conv_journal` — it had drifted). Re-run
   `scripts/ada/render-tool-profiles.py` for `ada-kk.env` /
   `ada-kk-dev.env` on idc03.
5. Gates: `python3 scripts/tool-lint.py`, `pytest tests/ -x -q`; the
   generator needs `CHABA_REPO` to point at a checkout containing
   `scripts/ada/trip-calendar.py` (default `~/CascadeProjects/chaba`,
   correct on idc03) or `TRIP_CALENDAR` for an explicit path.

### Contract

- `trip_calendar(slug, start?, end?, title?, keywords?, public?, confirmed?)`
- Lane binding by `ADA_CMS_COLLECTION` — ada-cms-pages→tony,
  -kk→kk, -kk-dev→kk-dev. The tool can't write another lane's CMS.
- `public='yes'` requires `confirmed='yes'` (explicit-ask rule, same as
  `cms_publish_page`'s public flag).
- Returns `{ok, rollup, leaves, days, events, collection, span,
  view_url, public_url, errors}` — the model answers with the link.

---

## Drop 2 — doc_read + LINE file ingest

Card `line-file-doc-ingest` (Tony 2026-10-13): a PDF sent to a lane over
LINE was dropped — `type:file` had no handler and `_MIME_EXT` archived
docs as `.bin`. This drop is the full ingest + read path.

### Files

- `backend/line_relay.file-doc-ingest.patch` — unified diff vs ada-pi
  `main` @ `1716db7`. Adds doc mimes to `_MIME_EXT` (pdf, doc/docx,
  xls/xlsx, csv, txt) and a `_MEDIA_INBOUND = ("file", "video")` branch
  in `handle_event`: fetch via the api-data content endpoint →
  `_archive_media` (durable `/relay-img/arch/` URL) → journal
  `kind=<mtype>` with name/mime/size → synthetic session turn
  `"[document received: <name> <mime> <url>] — doc_read can extract …"`.
  (Covers *every* remaining content-bearing LINE type — sticker/
  location/imagemap/template keep the refusal, they carry no blob.)
- `backend/tools.d/doc_read.py` — the read tool.
- `backend/tools.d/manifest.doc_read.yml` — merge under `tools:`.
- `backend/tool_guide.doc_read.yml` — append to `tool_guide.yml`.
- `tests/scenarios-live/doc_read.yaml` — coverage (lint bars new tools
  without a scenario reference).
- `docs/ssot/ssot.tool-surface.count_cap.patch` — count_cap 111→112
  (must land in the same ada-pi commit — the ratchet).

### Install (ada-pi worktree)

1. `cd <ada-pi> && git apply <chaba>/integrations/ada-pi/backend/line_relay.file-doc-ingest.patch`
   — base `1716db7`; if it no longer applies cleanly, re-dispatch the
   card rather than hand-merging hunks.
2. `cp <chaba>/integrations/ada-pi/backend/tools.d/doc_read.py backend/tools.d/doc_read.py`
3. Merge `manifest.doc_read.yml`'s `doc_read:` block into
   `backend/tools.d/manifest.yml` under `tools:`.
4. Append `tool_guide.doc_read.yml` to `backend/tool_guide.yml`.
5. `cp <chaba>/integrations/ada-pi/tests/scenarios-live/doc_read.yaml tests/scenarios-live/`
6. `git apply <chaba>/integrations/ada-pi/docs/ssot/ssot.tool-surface.count_cap.patch`
7. Tool profiles already updated in this repo —
   `docs/ssot/apps/ssot.apps.ada-persons.yml` adds `doc_read` to
   `persons.kk.tools.include`, `bench_profiles.kk-cms-only` and
   `kk-parity`. Re-run `scripts/ada/render-tool-profiles.py` for
   `ada-kk.env` / `ada-kk-dev.env` on idc03 **after** the ada-pi deploy
   (the env allowlist names a tool that must exist first, or
   tool-lint/persons-lint flags it undeclared).
8. Gates: `python3 scripts/tool-lint.py`, `.venv/bin/python -m pytest
   tests/ -x -q` — deploy-ada.sh runs both; then restart
   `ada-line-relay` + the kk/kk-dev lane units.

### Contract

- Relay: inbound `file`/`video` → archived under
  `LINE_MEDIA_ARCHIVE_DIR/<chat>/<msgId>.<ext>`, journal
  `{"dir":"in","kind":"file","url","name","mime","size"}`, persona turn
  `[document received: …]` — same routing gates as image turns (group
  needs a mention/default persona, DM needs an allowed user).
- `doc_read(path_or_url, prompt?)` — resolves the `/relay-img/arch/` URL,
  an archive-relative `<chat>/<file>` name, an img-cache nonce, or an
  absolute path **inside the media roots only**; inline-bytes →
  `gemini_pool.generate` (`ADA_DOC_READ_MODEL`, default
  `gemini-3.5-flash-lite`; 15 MiB cap via `ADA_DOC_READ_MAX_BYTES`).
  Returns `{ok, text, name, mime, bytes, source, model}`.
- Verified in-worktree by `tests/ada/test_line_file_doc_ingest.py`
  (chaba side): resolution confinement, archive round-trip, fake-gemini
  extraction, patch-applies + patched-file `handle_event` simulation.

---

## Drop 3 — calendar create dedup (idempotent writes)

Card `calendar-write-idempotency` (Tony 2026-10-13): a model retry /
double-invoke wrote the same kk-ha event twice 1s apart
(ทริปแอฟริกาใต้ BKK-CPT 2027-01-02). Same failure class as
`ada-tool-retry-storm` — the write path had no idempotency check.

### Files

- `backend/calendar_providers.create-dedup.patch` — unified diff vs
  ada-pi `main` @ `d166794`. Touches three files:
  - `backend/calendar_providers.py` — `CalendarService.create_event`
    now calls `_find_duplicate` first: resolves the write provider +
    target calid, lists that calendar's day window, and on a normalized
    title + identical-start match returns the existing event as
    `{..., dedup: true, existing: <qualified id>}` instead of creating.
    New helpers: `_norm_title` (NFC + casefold + collapsed whitespace —
    Thai combining sequences compare equal), `_event_start` (tolerant
    RFC3339/bare-date parse, `Z`-safe), `_dedup_start_key` (dates compare
    by day, datetimes by absolute instant so `+07:00`/`Z` spellings
    match). A failed dedup list propagates — same loud-fail rule as the
    reads; a blind create is exactly how the double-write happened.
  - `backend/tool_runner/calendar.py` — docstring on
    `calendar_create_event` noting the service-level dedup.
  - `tests/test_calendar_providers.py` — 7 new tests: dedup hit,
    title/instant normalization, all-day, different-calendar scope,
    no-match still creates, dedup-read failure is loud (no blind write),
    and an end-to-end `calendar_write` double-invoke through
    `ToolRunner.execute` (one provider write, second call returns
    `dedup: true`). `FakeProvider.create_event` now reflects creates
    into `list_events` (models real provider state).

### Install (ada-pi worktree)

1. `cd <ada-pi> && git apply <chaba>/integrations/ada-pi/backend/calendar_providers.create-dedup.patch`
   — base `d166794`; if it no longer applies cleanly, re-dispatch the
   card rather than hand-merging hunks.
2. Gates: `python3 scripts/tool-lint.py`, `.venv/bin/python -m pytest
   tests/ -x -q` — deploy-ada.sh runs both. No service restart beyond
   the normal deploy (the guard lives in the tool path).
3. Placement note: the guard sits in `CalendarService.create_event`, not
   the `tool_runner/calendar.py` wrapper named in the card — every write
   path (`calendar_write` action=create, the absorbed
   `calendar_create_event` alias, future non-tool callers) funnels
   there, and it's the only layer that already knows the resolved
   target calendar.

### Contract

- Identical create (same calendar, normalized title equal, same start
  instant/day) → returns the *existing* event dict plus `dedup: true`
  and `existing: <provider:calid/eid>`; no new event is written.
- Same title+start on a different calendar is not a duplicate.
- Verified against a /tmp clone of ada-pi `main` @ `d166794`:
  `tests/test_calendar_providers.py` 49/49 pass, `tool-lint` clean.

---

## Drop 4 — place_report (LINE maps link → public place page → link reply)

Card `maps-url-to-cms-line-maps-link-resolved-c418f8` (KNB-0574, Tonezzz
group directive 2026-10-12): members paste `maps.app.goo.gl` /
`google.com/maps` links in LINE asking "ร้านนี้ยังอยู่มั้ย" — one ask
should return a durable page link. Built and deployed directly in the
ada-pi repo on the same day; this drop stages the record copy.

**Status: DEPLOYED** — ada-pi `main` @ `074c7a8` (tool+manifest+guide+
coverage_debt) + `e24b14d` (token-stripping/name cleanup); live on
idc03 `ada-kk` since 2026-10-13 15:26; first real pages already on
`chaba.h3.gizmo-thailand.com/kk-ha/`. Verified end-to-end: LINE reply
POSTs 200, publisher timer shipped the pages (HTTP 200).

### Files (staged copies — byte-identical to deployed)

- `backend/tools.d/place_report.py` — the tool.
- `backend/tools.d/manifest.place_report.yml` — merge under `tools:`.
- `backend/tool_guide.place_report.yml` — append to `tool_guide.yml`.

### Install (only for a fresh ada-pi checkout / rebuild)

1. `cp <chaba>/integrations/ada-pi/backend/tools.d/place_report.py
   <ada-pi>/backend/tools.d/place_report.py`
2. Merge `manifest.place_report.yml`'s `place_report:` block into
   `<ada-pi>/backend/tools.d/manifest.yml` under `tools:`.
3. Append `tool_guide.place_report.yml` to `<ada-pi>/backend/tool_guide.yml`.
4. Add `place_report` to the ada-pi `coverage_debt` list in
   `docs/ssot/ssot.tool-surface.yml` (no scenario exists — debt, like
   ada-pi `074c7a8` did).
5. Lane env: `place_report` in `ADA_INCLUDED_TOOLS` (rendered —
   `docs/ssot/apps/ssot.apps.ada-persons.yml` already carries it) AND
   hand-set `ADA_CMS_PUBLIC_BASE=https://chaba.h3.gizmo-thailand.com/kk-ha/`
   in `~/.config/secrets/ada-kk.env` — the managed block doesn't cover
   it; without it `_cms_public_base()` falls back to the
   `surf-thailand.com/<tenant>-ha/` derivation, not the h3 Plesk site.
6. Gates: `python3 scripts/tool-lint.py`, `pytest tests/ -x -q` —
   deploy-ada.sh runs both; restart the lane unit after the env edit.

### Contract

- `place_report(url?, place?, ask?, lang?)` — expands maps shortlinks,
  parses `/place/<name>`/`!3d!4d` coords, Nominatim reverse/search
  enrich (no key), strips leading plus-code/house-number tokens from
  Google share strings, publishes `meta.public` markdown via
  `cms_publish_page` (domain `places`, `fresh_for=30d`), returns
  `{ok, slug, name, address, coords, resolved_url, publish{public_url}}`.
- Public pages land on `chaba.h3.gizmo-thailand.com/<tenant>/` via
  tony-dell's `cms-h3-publish.timer` (~15min cadence) — tell the user
  the link goes live within ~15min, or share the Google Maps link
  when they need it NOW (the tool's own note says this).
- Doc shape per `docs/kb/lane-place-reports.md` (card procedure
  `place-report`).

### Known gap — no dedup

The tool always publishes a fresh page keyed `place-<name>-<sha1(name|
coords)[:6]>`. Same place under different name spellings ⇒ duplicate
pages (observed: three `place-*jj-j-bistro*` pages in `ada-cms-pages-kk`
from the first live day). `lane-place-reports.md` rule 5 wants
cms_read-before-publish dedup; the tool doesn't do it and the
tool_guide doesn't tell the model to. Follow-up: teach the tool (or the
guide) to look up `place-<slug>`/name first and merge into the existing
page — keep History in one place.
