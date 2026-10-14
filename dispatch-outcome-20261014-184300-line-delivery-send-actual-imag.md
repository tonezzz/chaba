# Dispatch outcome — line-delivery-send-actual-images (verify + close)

Card: `line-delivery-send-actual-images-not-jus-652ad3` — was in `review`
(`review_kind: verify`, `verified: false`) after yesterday's dispatch
implemented, merged, and deployed ada-pi Drop 7. This run verified the fix
live and closed the card.

## What was verified (live on idc03, ada-line-relay journal since deploy ~2026-10-13 23:4x)

- Patched code deployed: `_mine_image_urls`, `_resolve_doc_media`,
  `_mined_msgs` present in `~/CascadeProjects/ada-pi/backend/line_relay.py`;
  service active (clean restarts only, NRestarts=0, no Failed entries).
- **7 real image deliveries** to chat `C822026077530a29620b5041bd1a955c5`:
  `[text,image,text]` at 12:39, 12:40, 12:57, 12:58, 17:13, 17:33, 17:52 —
  LINE now receives actual `image` message objects, not text links.
- **1 video delivery** `[video,text]` at 14:09.
- **Mining path confirmed firing**: a `/relay-img/arch/renders/*.mp4` ref in
  reply text was mined, fetched, content-type-rejected
  (`video/mp4, not an image`) and silently dropped → `[text]`-only delivery.
  Exactly the designed false-positive discipline.
- Env armed: `DOC_ARCHIVE_API_KEY` + `DOC_ARCHIVE_URL` in the relay env
  (Drive-share-link minting path live); `LINE_PUBLIC_IMG_BASE` serves public
  HTTPS via `https://157.85.102.125.sslip.io/relay-img`.
- Chaba-side drop merged into origin/master (a8078571 is an ancestor of
  this worktree's master baseline).
- Drive-link minting not yet exercised live (no Drive link in a reply since
  deploy) — covered by 18 unit tests; fires on next occurrence.

## Actions taken

- Posted verification evidence comment to the card (board-api).
- Closed the card via board-api `action do=close` → `moved to done`.
- No code changes in this worktree; nothing pushed.

## Notes / observations

- Journal shows heavy `relay-img MISS` spam at 17:37 (a Linux Chrome UA
  re-fetching expired transient `/relay-img/<nonce>` URLs — a CMS page or
  LINE client holding stale nonces). Pre-existing TTL behavior; durable
  images use `/relay-img/arch/`. Worth a card only if it recurs.

## How to re-verify

```
ssh idc03 'journalctl --user -u ada-line-relay --since "2026-10-13 23:30" \
  --no-pager | grep -E "deliver to|image .* failed"'
```
Look for `deliver to <chat>: [text,image,...]` entries; failures log as
`image <url> failed: ...`.
