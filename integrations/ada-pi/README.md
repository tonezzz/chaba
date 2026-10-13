# ada-pi drop-ins

Staged files for the **ada-pi repo** (`tonezzz/ada-pi`), produced by
chaba dispatches. Two drops live here:

1. `trip_calendar` — card `ada-trip-calendar-pages` (2026-10-13)
2. `doc_read` + line_relay file ingest — card `line-file-doc-ingest`
   (2026-10-13)

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
