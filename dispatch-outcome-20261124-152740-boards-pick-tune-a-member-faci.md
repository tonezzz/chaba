# Dispatch outcome — boards-member-theme-pick-tune (attempt 2)

## What happened

Attempt 1 (15:20–15:34 ICT) did the real work: live-compared five
wordpress.org themes on boards.surf-thailand.com, previewed Astra,
rejected Spectra (dead demo nav), and activated **Blocksy 2.1.62** as
its last act before the session cut off. Its branch auto-merged at
15:36 (landing `scripts/wp-boards/deploy-theme-zip.sh`) and merge-sweep
closed the card `done` at 15:38 — this attempt-2 dispatch was already
in flight, so the job became verify + document, not redo.

## Verified live (2026-11-24 ~15:45 ICT, from idc02)

- Theme: `wp-content/themes/blocksy` assets + `style.css` Version
  2.1.62 on every surface; header nav renders Boards / KK / Nhong /
  Tony.
- CPT archives all 200 with Blocksy entry-card lists (category chip,
  title, excerpt, author/date meta) + pagination:
  `/news/` `/place/` `/trip/` `/render_job/` `/activity/` `/nest_job/`,
  plus `/author/admin/` for member `post` type. Single news item
  renders full `entry-content`.
- By design, no archive index: `cam` (`has_archive=false` — per-camera
  directory posts are the browse surface; `/wp/cam/` 404 expected),
  `lesson` (301 → wiki Education per cutover), and the private-record
  CPTs (asset/expense/contact/reminder/bench/report/xlate/repeat_ask/
  ops_error/score/ops-event/timeline_block).
- Privacy unchanged: `/wp/chat/line/` anon → 404 (status gating is
  theme-independent); `/kk/` `/tony/` `/nhong/` public-by-design.

## Changed in this worktree

- `docs/ssot/apps/ssot.wp-boards.yml` — new `theme:` section recording
  the pick, evaluated candidates, deploy/rollback path, archive map,
  and privacy note; `last_updated` → 2026-11-24.
- `docs/ssot/jobs/cms/2026-11-24-wp-boards-member-theme.yml` — decision
  + verification trail (attempt-1/attempt-2 split documented).

Already on master from attempt 1's merge (not re-added):
`scripts/wp-boards/deploy-theme-zip.sh` — wp-admin theme-upload deploy
tool, runs on tony-omen which holds the wp-admin credential.

## How to verify

- `curl -s https://boards.surf-thailand.com/wp/news/ | grep -o 'wp-content/themes/[a-z-]*'` → `blocksy`
- Open `/wp/news/`, `/wp/place/`, `/wp/trip/`, `/wp/nest_job/` — card
  lists with excerpts + pagination.
- `docs/ssot/apps/ssot.wp-boards.yml#theme` for the recorded decision.

## Notes / gotchas

- board-api is NOT on localhost:8787 from idc02 — use
  `https://idc03.taila0626a.ts.net:10000` (tailnet front).
- The card was already `done` when attempt 2 ran; card comms posted
  via the tailnet endpoint anyway for the audit trail.
- No further live tuning was needed — Blocksy's defaults already meet
  the "readable archives" bar; deeper cosmetic tuning would need
  wp-admin on tony-omen and is Tony's call, not a dispatch gate.

lessons:
- Dispatch attempt N+1 can start before attempt N's merge-close lands — always re-check live state + card column first; this run was verify-only.
- board-api from non-idc03 hosts: http://127.0.0.1:8787 refuses; use https://idc03.taila0626a.ts.net:10000.
- WP boards theme/plugin deploys have no SSH/WP-CLI door — wp-admin upload scraping via tony-omen creds is the only path (deploy-plugin-zip.sh / deploy-theme-zip.sh).
- CPT archive coverage is per-post-type `has_archive` in chaba-boards.php — a 404 archive (e.g. /wp/cam/) is by design, not a theme regression.
