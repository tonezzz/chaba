# Dispatch outcome — line-file-doc-ingest (attempt 2)

**Card:** `line-file-doc-ingest` — Tony sent Kaewta a PDF trip ticket
over LINE; `type:file` messages had no handler in `line_relay.py` and
`_MIME_EXT` only mapped audio/video, so docs were dropped / would
archive as `.bin`.

## What changed (all in this worktree, commit 92bd5aad8)

The ada-pi repo isn't in this worktree, so — following the
`integrations/ada-pi/` staging convention set by the trip_calendar drop
— the deliverable is a complete staged drop plus the chaba-side SSOT
updates:

- `integrations/ada-pi/backend/line_relay.file-doc-ingest.patch` —
  unified diff vs ada-pi `main` @ `1716db7`:
  - `_MIME_EXT` += pdf, doc/docx, xls/xlsx, csv, txt
  - `_MEDIA_INBOUND = ("file", "video")` — covers every remaining
    content-fetchable LINE type (sticker/location/imagemap/template have
    no blob, keep refusal)
  - media branch in `handle_event`: `_fetch_content` (api-data.line.me)
    → `_archive_media` (durable `/relay-img/arch/` URL) → journal
    `{kind: file, url, name, mime, size}` → synthetic session turn
    `"[document received: <name> <mime> <url>] — doc_read can extract…"`;
    octet-stream payloads re-guess mime from `fileName`
- `integrations/ada-pi/backend/tools.d/doc_read.py` — new tool:
  `doc_read(path_or_url, prompt?)` resolves `/relay-img/arch/` URLs
  (absolute or host-relative), archive-relative `<chat>/<file>` names,
  img-cache nonces, or absolute paths — **confined to the two media
  roots** (`LINE_MEDIA_ARCHIVE_DIR`, `LINE_IMG_CACHE_DIR`) — reads bytes
  → `gemini_pool.generate` inline `Part` (no new deps; PDF/CSV/TXT
  native, mp4 ok) → `{ok, text, name, mime, bytes, source, model}`.
  `ADA_DOC_READ_MODEL` (default gemini-3.5-flash-lite),
  `ADA_DOC_READ_MAX_BYTES` (15 MiB).
- `manifest.doc_read.yml` (read / secondary_allowed / 60s),
  `tool_guide.doc_read.yml`, `tests/scenarios-live/doc_read.yaml`,
  `ssot.tool-surface.count_cap.patch` (111→112 — the ratchet).
- `docs/ssot/apps/ssot.apps.ada-persons.yml` — `doc_read` added to
  `persons.kk.tools.include`, `bench_profiles.kk-cms-only`, `kk-parity`
  (renders ADA_INCLUDED_TOOLS for kk/kk-dev — after ada-pi deploy).
- `integrations/ada-pi/README.md` — restructured as a drop index; Drop 2
  section = the install runbook.
- `docs/ssot/jobs/ada/2026-10-13-line-file-doc-ingest.yml` — job trail.
- `tests/ada/test_line_file_doc_ingest.py` — 14 tests.

## Result / verification

- `pytest tests/ada/` → **37 passed** (14 new). The relay tests apply the
  patch to the live ada-pi source (`git apply --check` clean), compile
  it, and drive `handle_event`: DM file → `arch/U1/m1.pdf` written,
  journal `kind=file` with name/mime/size/url, session got the
  `[document received: …]` turn, reply delivered; video same path;
  sticker still refused; path traversal + outside-root reads refused;
  fake-gemini asserted the inline part bytes+mime.
- `ssot-validate-all.mjs` → 2191 files, 0 errors.
- Not deployed (rails). Live verify post-install: send a PDF to the
  kk-dev lane → journal `kind=file`, arch URL 200, ask "what does that
  document say" → doc_read extracts fields.

## Loose ends for the landing session

- Attempt 1's ada-pi worktree (`dispatch-wt-20261013-100510-…`) still
  holds its abandoned uncommitted `line_relay.py` diff — `git restore`
  it when landing this drop.
- Render order matters: `render-tool-profiles.py` for ada-kk/ada-kk-dev
  env only **after** the ada-pi deploy declares doc_read (lint flags
  undeclared allowlist names).

lessons:
- Card specs naming `backend/…` files are ada-pi paths; chaba-side
  dispatches deliver via `integrations/ada-pi/` staged drops (+patch for
  existing files), never by editing `~/CascadeProjects/ada-pi` — writes
  outside the worktree risk session kill.
- tools.d modules lazily import `google.genai` inside `run()` — test
  stubs must stay in `sys.modules` for the whole test, not just import.
- New ada-pi tools need THREE same-commit companions or gates fail:
  manifest entry, `count_cap` bump in `docs/ssot/ssot.tool-surface.yml`,
  and a `tests/scenarios-live/*.yaml` reference (coverage_debt lint).
- LINE `file`/`video` are the only remaining content-fetchable types;
  `video` had no handler either — it rides the same ingest branch now.
- A patched-media message in a group still routes through `_route("")`
  — unmentioned rooms stay silent, matching image semantics.
