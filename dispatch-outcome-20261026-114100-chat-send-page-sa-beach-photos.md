# Dispatch outcome — chat_send page=<slug> (CMS page images server-side)

Card: `chat-send-page-images` (ADA-0511)
Runner: mn01 · 2026-10-26

## What was built

The card asked for a structural fix to Kaewta's nondeterministic
photo-ask handling (cms_read + image_url + deliver sometimes invented
URLs → 404s, or produced text-only phantom sends). `chat_send` now
takes `page=<cms slug>`: the tool reads the page itself inside the
background job, extracts every embedded image, and sends the batch —
one call, no URLs for the model to fabricate, and the result note
reports sent/failed per asset so her voice stays honest.

Delivered as ada-voice **drop 15** under `integrations/ada-voice/`
(base `main` @ `56c67c1`, cloned into `.scratch/` inside the worktree —
no ada-voice checkout exists on mn01):

- `tool_runner.page-images.patch` — `chat_send(..., page: str = "")`;
  `page` short-circuits to `_chat_send_page`/`_chat_send_page_run`
  (same 'queued' contract). `_page_image_urls` extracts markdown
  `![..](..)` + HTML `<img src>` in document order, dedupes, resolves
  absolute + site-relative vs `LINE_URL_BASE` (same default the relay
  fetches against), caps at `ADA_CHAT_PAGE_IMG_MAX` (default 10). The
  job POSTs `{text, image_urls:[...]}` to the lane relay and folds the
  response's `images` list into a per-asset sent/failed summary.
  `say=` rides the same payload; `web` channel delivers per-asset via
  `_chat_send_web`. Say-audio + notify tails of `_chat_send_run`
  factored into shared `_chat_say_audio`/`_chat_notify` — no
  plain-path behaviour change. `image_url=` untouched for ad-hoc URLs.
- `line_relay.page-images.patch` — `/send` accepts `image_urls`: each
  URL becomes its own image bubble via `_image_msgs` (failures keep the
  honest `(image failed)` text bubble). Delivery chunks into
  consecutive ≤5-msg pushes — the old `msgs[:5]` truncate silently
  dropped the tail of ANY stacked payload, not just batches. Bulk class
  now parks the full msg list (`_merge_msgs` re-chunks on flush).
  Response gains `images:[{url,ok,status}]` —
  delivered|parked|failed|fetch-failed per asset; `image_url` gets the
  same report entry free.
- `tg_relay.page-images.patch` — `/send` accepts `image_urls` → one
  `send_photo` per asset with the same `images` report; `send_photo`
  now returns delivery bool (callers ignore it).
- `realtime_provider.page-images.patch` — `page` added to the chat_send
  declaration (required — `additionalProperties: false` would reject
  the arg); `image_url` description now points CMS-image asks at
  `page=`.
- `tool_guide.page-images.patch` — guide entry documents `page=`.
- `tests/test_chat_send_page.py` — ada-voice suite (17 tests).
- `tests/ada/test_chat_send_page.py` — chaba-side drop gate (tri-state
  apply/compile + surface assertions).
- `integrations/ada-voice/README.md` — drop 15 section (install +
  contract + restart-order note).
- `docs/ssot/jobs/ada/2026-10-26-chat-send-page-images.yml` — trail.

## Side fix found while verifying

Running `tests/ada` with a real checkout surfaced a genuine bug in the
staged **drop 14** (`tg_relay.forward-provenance.patch`, still
pending): its new forwarded-media branch falls through to the shared
`if turn_ok:` tail without ever initializing `turn_ok` —
`UnboundLocalError` on any forwarded document/sticker. Patched the
staged patch (+2 lines: `turn_ok = False` before the try, `True` after
`send_turn`); its test now passes 16/16.

## Verified

- ada-voice `main` @ `56c67c1` + patches (fresh clone):
  `tests/test_chat_send_page.py` 17/17; neighbours
  `test_tool_runner` + `test_line_relay_group` +
  `test_line_relay_quota` + `test_line_reply_context` +
  `test_tg_relay_*` = **361 passed**; `scripts/tool-lint.py` clean
  (only a pre-existing coverage-debt warning on chat_send).
- All 5 patches `git apply --check` clean against pristine base
  (verified via stash/check/restore).
- Chaba side: `pytest tests/ada` with `ADA_PI=.scratch/ada-voice` —
  **197 passed, 4 skipped** (env skips; without ADA_PI the same suite
  skips the checkout-dependent tests as designed — one pre-existing
  unguarded failure in `test_line_image_delivery.py` on hosts with no
  checkout, unrelated to this drop).
- NOT verified live: no real LINE push. First
  `chat_send(page='sa-beach-photos')` after deploy is the smoke —
  check relay log `send: inst=… msgs=N` and the note's per-asset count.

## Not done / follow-ups

- Not pushed, not deployed (dispatch rules). Install per README
  drop 15: `git apply` the five `*.page-images.patch`, copy
  `tests/test_chat_send_page.py`, `deploy-ada.sh` — restart lanes AND
  `ada-line-relay`/`ada-tg-relay` together (a new lane on an old relay
  degrades to 'delivered (no per-asset report)' — still honest).
- `.scratch/` added to `.gitignore` (dispatch scratch clones).
- Pre-existing gap noted: `tests/ada/test_line_image_delivery.py`
  lacks the `NEEDS_ADA_PI` skip guard its siblings have — errors on
  hosts without an ada-voice checkout. Worth a card someday.
