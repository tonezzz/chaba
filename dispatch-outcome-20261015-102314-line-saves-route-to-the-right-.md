# Dispatch outcome — LINE saves route to the right WP CPT

Card: `line-cpt-writer-router` (OPS-0656, medium)
Result: **done — staged as ada-voice Drop 11 (3 patches + chaba tests),
committed on the dispatch branch. Not pushed, not deployed — the ada-voice
apply + deploy needs the normal deploy-ada.sh lane.**

## What changed

boards.surf-thailand.com's chaba-boards CPTs (asset, expense, contact,
reminder, …) are live and REST-writable since 2026-10-14, but every LINE
"post this / save this" ask still landed as a free-form post. Rather than
a new `cpt_post` tool, the existing `wp_post` tool gains `kind=` + `meta=`
— one entry point keeps the tool surface flat (no count_cap bump) and the
member verb unchanged.

- `integrations/ada-voice/backend/tools.d/wp_post.cpt-router.patch` —
  vs ada-voice `main` @ `8eaab27`. kind = post|expense|contact|reminder|
  asset (default post = byte-identical old behavior: public post + person
  tag + tag_archive). `meta` is whitelisted to the plugin-registered keys
  per kind (`_KIND_META`); unlisted keys are dropped and reported via
  `dropped_meta`. kind=expense + media_url runs `_ocr_receipt` — the
  archived LINE photo/PDF goes inline to `gemini_pool.generate`
  (ADA_WP_OCR_MODEL, default gemini-3.5-flash-lite; ADA_WP_OCR_MAX_BYTES
  8 MiB) asking strict JSON for amount/currency/vendor/receipt_date/
  paid_by; caller fields always win, OCR failure is silent (record still
  lands). CPT records publish `private` (member-only — household
  expenses/contacts never enter the public post stream) and get the
  `<Kind> — <title>` title_standard prefix automatically. Non-image media
  (asset manual PDF) embeds as an attachment link; featured_media is set
  only for image uploads.
- `integrations/ada-voice/backend/tool_guide.wp_post-cpt.patch` — kind
  routing per ask type, per-kind meta keys, kk-lane convention (KK runs
  the household — 'remind us' defaults assignee=kk), private-status
  semantics, "pass the bare title".
- `integrations/ada-voice/tests/scenarios-live/wp_post.cpt.patch` — two
  draft-mode turns (reminder + contact) exercising the CPT route on the
  live tier.
- `tests/ada/test_wp_post_cpt_router.py` — 11 tests (post regression,
  OCR fill/override/failure, meta whitelist + dropped keys, private
  status, title prefix, PDF-as-link, invalid kind, draft, missing media).
- `docs/ssot/apps/ssot.wp-boards.yml` — writers.wp_post documents the
  CPT router.
- `docs/ssot/jobs/ada/2026-10-15-line-cpt-router.yml` — job record.
- `integrations/ada-voice/README.md` — Drop 11 section + index entry.

## Sweep fixes (pre-existing breakage found while verifying)

- `tests/ada/test_draft_hit_frame.py`, `test_line_image_delivery.py`,
  `test_line_reply_routing.py` — all three failed because their drops
  (6/7/8) are already merged upstream (ada-voice `02c5058` + earlier) so
  the patch gates could never apply again. Added the same merged-marker
  fallback drop-2's test already uses: `git apply --check` fails → assert
  a feature marker exists in the live file → exercise the merged file.
  Also normalized one `_images_from` assertion — upstream now returns
  (url, cap, kind) triples.
- `docs/ssot/jobs/kanban/2026-10-15-board2-living-board.yml` — bare `#`
  in a plain scalar (`— #ticker`) started a comment and broke YAML
  parsing (the lone ssot-validate-all error); quoted it.

## Verified

- `pytest tests/ada/` — **111 passed** (was 6 failed + 26 errors before
  the sweep fixes).
- `git apply --check` on ada-voice `main` @ `8eaab27` — all three staged
  patches apply cleanly.
- `node scripts/ssot-validate-all.mjs` — 2410/2411 valid (the one error
  was the board2 file, now fixed; residual warnings are pre-existing
  bloat notices).
- wp_post DECLARATION description: 236 chars < 300 cap; ≤4 lines.

## To land it (install on ada-voice worktree)

1. `cd <ada-voice> && git apply` the three Drop 11 patches (README has
   the exact commands).
2. Gates: `python3 scripts/tool-lint.py`, pytest — deploy-ada.sh runs
   both; restart the lane units (tools.d reload; relay untouched). No
   manifest/persons/count_cap change — same tool name, new optional
   params.
3. No WP-side change needed — the plugin already registers every meta
   key used.

## Residual / judgement calls

- "KK is boss of kk-hom" was implemented as a guide-level convention
  (reminder assignee defaults to kk on her lane), not a code gate — the
  lane policy layer already scopes callers and CPT meta carries no
  authority semantics. If a per-member meta axis is wanted later (e.g.
  `for_member` admin column), that's a chaba-boards plugin bump.
- OCR depends on the lane's Gemini free pool — on quota exhaustion the
  record still lands, just without the auto-filled fields (and the
  reply carries `ocr: null`).
