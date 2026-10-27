# Dispatch outcome — create tony-ha timeline (HOM-0647)

## Result: already shipped — verified live, card closed

The "tony-ha timeline" Tony asked for in the LINE group on 2026-10-14
14:46 was built live in the same minute: WP **page 71 "tony-ha timeline"**
(private, under the `chat > line` tree on boards.surf-thailand.com) backed
by **timeline_block 69 "tony-ha LINE chat"**, synced every 5 min by
`line-chat-timeline.timer` on idc03 (LANES map:
`tony-ha -> C4fb0ce548a58e2d758335b7e21ce3411, block 69`). The card was
never closed and sat in backlog for 13 days.

## Verification (surface + producer, 2026-10-27)

- WP REST `pages/71` → `"tony-ha timeline"`, status private, parent 33,
  modified 2026-10-14T07:47Z (one minute after the ask).
- WP REST `timeline_block/69` → `"tony-ha LINE chat"`, private,
  **modified 2026-10-26T22:37** — still being rebuilt.
- idc03: `line-chat-timeline.timer` fired 05:37 ICT today; state file
  `wp-timeline-state.json` touched same minute.
- LINE journal `~/.local/share/ada/line-media/C4fb0ce…/journal-2026-10-17.jsonl`
  — newest message 2026-10-17 (group idle, not a pipeline break).

## Actions taken

- Card comment with evidence → `/action do:close` → moved to done.
- Follow-up filed **HOM-0918** `house-timeline-orphaned-feed-repoint`:
  the *other* tony-ha-adjacent timeline (`house-timeline` family in
  ada-cms-pages) is orphaned — `house-timeline.timer` is gone with the
  tony-dell drain (pages frozen 2026-10-13) and `kind=events` docs in
  `ada-ha-events-tony` stalled 2026-10-23 (ops-event stream still flows).
  Needs a new timer home + events-collector repoint to the current HA URL.
- Trail record: `docs/ssot/jobs/cms/2026-10-27-tony-ha-timeline-verify-close.yml`.

## How to verify

- Surface: `GET https://boards.surf-thailand.com/wp/wp-json/wp/v2/pages/71`
  (auth) → `"tony-ha timeline"`; members see it at `/wp/chat/line/tony-ha/`.
- Producer: `ssh tony@idc03 systemctl --user list-timers line-chat-timeline.timer`.
