# Dispatch outcome — LINE delivery: send actual images, not just text links

Card: `line-delivery-send-actual-images-not-jus-652ad3` (ADA-0608, high)
Result: **done — staged ada-pi Drop 6, tested, committed on the dispatch
branch (not pushed, not deployed).**

## What was wrong

LINE journal 2026-10-13 21:35: "ส่งรูปรถของผมให้หน่อย" → the persona ran
`drive action='search' mime='image/'`, got a `webViewLink` (an HTML
viewer page, not bytes), and pasted it into reply text. LINE delivered a
text link. Three structural gaps in `backend/line_relay.py`:

1. `_images_from()` only checked `cast_url`/`image_url`/`url` result keys
   — never `drive_get`'s `media_url`, never the reply text.
2. Nothing knew how to fetch a Drive share link (it's HTML; direct GET
   gives a viewer page).
3. `/v1/drive/media/` host-relative URLs resolved against the wrong base
   (`LINE_URL_BASE` instead of `DOC_ARCHIVE_URL`).

## What changed (staged patches vs ada-pi `main` @ `bb4c172`)

- `integrations/ada-pi/backend/line_relay.image-delivery.patch`
  - `_resolve_doc_media()`: Drive share links (`file/d/`, `open?id=`,
    `uc?id=`, `docs/<app>/d/`) mint fetchable `/v1/drive/media/<id>?t=`
    URLs via doc-archive `POST /v1/drive/media-token` (relay env already
    carries `DOC_ARCHIVE_API_KEY`); `/v1/drive/media/` resolves against
    `DOC_ARCHIVE_URL`. Runs inside `_image_msgs`'s try so failures are
    non-fatal.
  - `_mine_image_urls()` + `_mined_msgs()`: scan reply text and `/send`
    text for image-bearing refs (image extensions, Drive links,
    `/v1/drive/media/`, `/relay-img/`), dedupe against structured tool
    images, deliver as real LINE `image` messages. Mined failures are
    silent — the link stays in the text either way.
    `LINE_TEXT_IMG_MINE=0` disables. Wired into all four reply paths and
    `/send`.
  - `_images_from()` accepts `media_url` when `mimeType` is `image/*` —
    `drive_get` on an image auto-attaches the photo.
- `integrations/ada-pi/backend/tool_guide.image-delivery.patch` —
  `chat_send image_url=` documented as needing a real image file or
  Drive link (never a CMS page URL); `drive` guide explains `media_url`.
- `integrations/ada-pi/backend/realtime_provider.image-delivery.patch` —
  `image_url` schema description updated the same way.
- `integrations/ada-pi/README.md` — Drop 6 section (files, install,
  contract, residuals).
- `docs/ssot/jobs/ada/2026-10-13-line-image-delivery.yml` — job record.
- `tests/ada/test_line_image_delivery.py` — 18 tests.
- `tests/ada/test_line_file_doc_ingest.py` — harness fix: the drop-2
  patch is already merged upstream (ada-pi `6148f64`), so it can never
  apply again; the fixture now detects merged markers and exercises the
  upstream file, plus stubs httpx/websockets like the new test.

## Verification

- `pytest tests/ada/` → **72 passed** (scratch venv `.cache/venv` with
  httpx+websockets installed; `ADA_PI=.cache/ada-pi-verify` — a pristine
  ada-pi clone at `bb4c172`, gitignored).
- Patches verified to apply cleanly (`git apply --check`) against a
  pristine `bb4c172` tree and the patched sources compile.
- Live check done earlier: doc-archive `media-token` mint returns a URL
  serving the real 4.5MB JPEG; `ada-line-relay`'s env file already
  carries `DOC_ARCHIVE_API_KEY`.

## To ship

Apply the three patches on tony-dell's ada-pi checkout (README Drop 6),
commit + push, deploy-ada.sh on idc03 (runs tool-lint + pytest gates),
restart `ada-line-relay`. `LINE_TEXT_IMG_MINE=0` reverts to old behavior.

## Residuals / notes

- Minted media URLs are short-lived but fetched immediately and
  re-hosted via `/relay-img/` — TTL only gates the initial fetch.
- LINE batches cap at 5 messages (unchanged); excess links stay text.
- Paired card `line-tool-reply-routing-answers-leave-th-5c73e7`
  (session drops) is a separate routing fix — untouched here.
