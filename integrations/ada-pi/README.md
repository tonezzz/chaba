# ada-pi drop-ins

Staged files for the **ada-pi repo** (`tonezzz/ada-pi`), produced by
chaba dispatches. Five drops live here:

1. `trip_calendar` — card `ada-trip-calendar-pages` (2026-10-13)
2. `doc_read` + line_relay file ingest — card `line-file-doc-ingest`
   (2026-10-13)
3. calendar create dedup — card `calendar-write-idempotency` (2026-10-13)
4. `place_report` — card `maps-url-to-cms-line-maps-link-resolved-c418f8`
   (2026-10-13) — **already deployed** (ada-pi `074c7a8`+`e24b14d`); this
   drop is the repo-of-record copy
5. file-input speaker ID + LINE enroll-on-clips + boss rule — card
   `line-voice-enroll-recognize` (2026-10-13)

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

**Status: DEPLOYED, then patched here (2026-10-13, card
place-report-empty-page)** — ada-pi `main` @ `074c7a8` (tool+manifest+
guide+coverage_debt) + `e24b14d` (token-stripping/name cleanup); live
on idc03 `ada-kk` since 2026-10-13 15:26; first real pages already on
`chaba.h3.gizmo-thailand.com/kk-ha/`. Verified end-to-end: LINE reply
POSTs 200, publisher timer shipped the pages (HTTP 200). **The staged
`place_report.py`/`tool_guide` below now carry the empty-page guard and
are AHEAD of the deployed copy** — redeploy per Install to land it.

### Files (staged copies)

`place_report.py` and `tool_guide` carry the 2026-10-13 empty-page
guard and are ahead of the deployed ada-pi copies; the manifest
fragment is still byte-identical.

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
- **Unresolved guard** (2026-10-13, card `place-report-empty-page`):
  a bare `place=` that Nominatim can't pin down has neither coords nor
  a maps link — publishing there produced title-only pages
  (`place-cape-sports-center-langebaan-*`). `run()` now returns
  `{ok:false, unresolved:true, name, maps_url, error}` and publishes
  nothing; `maps_url` is a `maps/search/?api=1&query=<name>` fallback
  for the chat reply. A `url=` that resolved to a real maps link still
  publishes even with no coords — that page carries a working link.
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

---

## Drop 5 — file-input speaker ID (LINE voice enroll + recognize + boss rule)

Card `line-voice-enroll-recognize` (Tony 2026-10-13): members send a few
voice clips over LINE to enroll; the lane then recognizes who is
speaking on voice messages (boss recognition — completes the MEM-0572
identity leg). Gap closed: every match/enroll path previously required a
LIVE session voice buffer; file input did not exist (a `speaker_profiles
match` on a LINE session 2026-10-13 19:41 failed for exactly this).

### Files

- `backend/speaker_id.file-input.patch` — `backend/speaker_id.py`.
  New `decode_audio_file()` (PyAV → PCM16 mono 16k, ffmpeg-CLI fallback,
  `ADA_SPEAKER_FILE_MAX_S` cap, default 120s), `embed_file(path)`,
  `match_file(path)` → `{match, score, all_scores, best, ha_person…}`
  reusing the same threshold+margin+media-pool logic
  (`_identify_scored_core` gained an optional `emb=` so the embedding
  computes once), and `enroll_from_file(path, name, person)` — `person`
  normalizes `user-kk`/`kk`/`person.kk`. Same guards as `enroll()`:
  EnrollConflict on a foreign-profile match, own-voice check on merge.
  `score_audio` shares the new `_rank_scores` helper.
- `backend/line_relay.voice-enroll-recognize.patch` —
  `backend/line_relay.py`. Every saved clip is scored via
  `match_file` (env `LINE_VOICE_MATCH=0` disables); the persona turn
  gets a `[voice: speaker=<name|unknown> score=0.xx person=…]` context
  line. Unknown voice on a caller-mapped lane arms the enroll-on-clips
  flow (`LINE_VOICE_ENROLL=1` default, `LINE_VOICE_ENROLL_CLIPS=3`,
  `LINE_VOICE_ENROLL_TTL_S=900`): each subsequent clip becomes one
  voiceprint bound to the caller's `person.*`; completion acks
  `enrolled <name>, 3 prints`. A recognized voice (any profile) closes
  the pending flow; an EnrollConflict disarms it loudly. New env vars
  documented in the module header.
- `backend/speaker_profiles.file-actions.patch` —
  `backend/tools.d/speaker_profiles.py`. New `action='match_file'`
  (read-tier, `path=`) and `action='enroll_file'` (mutating — same
  `_may_mutate` gate as re-enroll: full-access identity or the profile
  bound to the caller's own person.*). `person=` resolves through HA
  like `alias` does.
- `backend/tool_runner.boss-rule.patch` —
  `backend/tool_runner/__init__.py`. Boss rule: a positively-identified
  speaker whose person policy is `{full: true}` (persons.yml
  `role: admin`, i.e. person.tony) keeps owner-tier on ANY lane —
  `_speaker_is_owner_tier()` feeds both `_is_secondary_turn` (not
  secondary) and `policy_identity` (resolves to the speaker's own
  identity). Stale labels (SPEAKER_STALE_S) don't elevate.
- `backend/tool_guide.speaker-profiles-file.patch` —
  `backend/tool_guide.yml`. Documents match_file/enroll_file, the 0.45
  threshold + 0.05 margin, the boss rule, and the spoofing caveat (a
  voiceprint is evidence, not authentication — replay/similar-voice
  residual).
- `backend/test_line_relay_group.voice-ack.patch` —
  `tests/test_line_relay_group.py`. The saved-clip ack is now
  speaker-aware; the old literal "Saved Ns voice clip to the corpus."
  expectation becomes the enroll offer.
- `tests/test_speaker_file_input.py` — NEW FILE, 30 tests: decode
  (real WAV via PyAV, resample/cap/too-short/ffmpeg fallback),
  `_person_entity`, match_file hit+miss, enroll roundtrip (3 clips →
  4th matches), `_voice_context` strings, relay arm→enroll→confirm
  flow, tool actions incl. the mutation gate, and the boss rule
  (elevation, stale-label, fail-closed).

### Install (ada-pi worktree)

1. `cd <ada-pi> && for p in speaker_id.file-input \
   line_relay.voice-enroll-recognize speaker_profiles.file-actions \
   tool_runner.boss-rule tool_guide.speaker-profiles-file \
   test_line_relay_group.voice-ack; do git apply \
   <chaba>/integrations/ada-pi/backend/$p.patch; done`
   — based on the idc03 checkout @2026-10-13; if a hunk no longer
   applies, re-dispatch the card rather than hand-merging.
2. `cp <chaba>/integrations/ada-pi/tests/test_speaker_file_input.py
   tests/test_speaker_file_input.py`
3. Gates: `python3 scripts/tool-lint.py`, `.venv/bin/python -m pytest
   tests/ -x -q` — deploy-ada.sh runs both; restart `ada-line-relay`
   (the voice-match + enroll flow) along with the normal units.
4. No new dependencies — decode uses the already-pinned `av` package
   (bundled ffmpeg libs; idc03 has no ffmpeg binary).

### Contract

- Voice clip arrives → archived to `voice-corpus/<caller>/` (unchanged)
  → `match_file` → persona turn tagged
  `[voice: speaker=KK score=0.62 person=person.kk]`; the persona names
  the speaker and can route `person_entity` → scoped bank.
- Unknown + mapped caller → offer text ("send me 2-3 short clips") +
  armed pending enrollment; each clip enrolls one print under the
  caller's person; acks progress; final `enrolled <name>, N prints`.
- `speaker_profiles action='match_file' path=<clip>` /
  `action='enroll_file' path=<clip> name=<profile> person=<p>` for
  ops/testing and persona-driven enrollment.
- Boss rule: person.tony recognized on any member lane keeps
  owner-tier identity per persons.yml `role: admin` ({full: true} in
  person/control policies). Recognition threshold stays
  `ADA_SPEAKER_THRESHOLD` (default 0.45) + 0.05 margin — documented
  with the spoofing caveat in the tool guide.
- Verified on a clean copy of the idc03 ada-pi checkout:
  `tool-lint` clean, `pytest tests/` 1360 passed incl. the 30 new
  tests; `decode_audio_file` verified against real LINE corpus m4a
  clips on idc03.

### Notes / residual

- LINE m4a clips of already-enrolled speakers score LOWER than
  live-mic captures (channel codec + whole-clip embedding). The two
  2026-10-13 user-kk corpus clips score below threshold — expected to
  resolve once callers enroll FROM LINE clips (channel-matched
  prints), which is exactly what the enroll flow bootstraps.
- The pending enroll is in-memory per relay process — a restart mid-
  flow just re-arms on the next unknown clip.
- The `[voice:]` context line is attribution for the persona, not an
  auth upgrade for the LINE lane — lane rights stay caller-keyed.
