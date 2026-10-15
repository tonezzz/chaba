# dispatch-outcome 20261015-102321 — wp-comment-sync: member comments -> agent suggestion lanes

## What changed

- **`scripts/ada/wp-comment-sync.py`** (new) — polls `GET /wp/v2/comments?after=<cursor>`
  on boards.surf-thailand.com, routes each new comment by the commented post's
  REST type (resolved via `_links.up`):
  - `memory-mirror`/`memory_mirror` → **Ada suggestion queue**: writes
    `~/.local/share/ada/memory-pending/mp-wpc<comment_id>.yml` in the exact
    `backend/memory_pending.py` schema — the existing approver surface
    (`memory-pending.py list/approve/reject`) sees it unchanged; deterministic
    id = idempotent re-staging; `route: bank` + sha256 pin so approval applies
    through the guarded write path, never directly.
  - `asset`/`place`/`trip` → **record-corrections queue**:
    `~/.local/share/wp-comment-sync/record-corrections/corr-<id>.yml` —
    an agent applies the correction to the record; nothing is auto-applied.
  - `cam`/`bench`/`render_job` + all other types → **digest only**:
    `digest.jsonl` line; every routed comment also gets an `events.md` line
    (kind `wp-comment`).
  - **Ack**: in-thread REST reply naming the lane + queue id, with an
    `<!-- wcs-ack -->` marker.
  - **Dedup/cursor**: `state.json` holds the `date_gmt` cursor plus bounded
    `processed[]`/`acks[]` id sets (comment-meta `_processed` skipped per card
    help). Our own ack replies are skipped via `acks[]` + marker. Route → mark
    processed → ack ordering means a failed ack can never double-route.
    Non-blocking flock prevents timer overlap.
  - **Comments are SUGGESTIONS only** — no MDDB writes, no post edits.
- **`docs/ssot/infrastructure/ssot.jobs.yml`** — `wp-comment-sync` job: idc03,
  `every: 15m`, `timeout: 2m`, `persistent`, `condition_path` gate.
- **`scripts/render-jobs.py`** — new optional `condition_path` job field →
  `ConditionPathExists=` in `[Unit]`: the unit is skipped (not failed) while
  the ExecStart file is absent — reusable for any job whose script lands via
  a not-yet-merged branch.
- **`systemd/generated/idc03/wp-comment-sync.{service,timer}`** — rendered;
  installed to `~/.config/systemd/user/` on idc03 and **enabled** (next run
  10:45). Verified: `ConditionPathExists` cleanly *skips* while the script is
  absent from the served checkout — no fail-state, no timer-sentinel alert.
  The timer self-activates when this branch merges + the checkout pulls.
- **`docs/ssot/jobs/ada/2026-10-15-wp-comment-sync.yml`** — full runbook:
  lanes, mechanics, file map, verify evidence, follow-ups.
- **Board**: progress + findings comms on `wp-comment-sync-suggestion-inbox`;
  follow-up card `wp-board-cpt-comments-open` (KNB-0697) filed.

## Verified live on idc03

- Test comment on news post 361 → routed to digest lane (`digest.jsonl` line),
  ack reply posted in-thread (marker present), `events.md` line, cursor advanced.
- Second run fetched the ack reply and skipped it via `acks[]` — 0 routed, no
  reply-to-ack loop.
- Synthetic runs exercised the other lanes: `corr-*.yml` and `mp-wpc*.yml`
  match the documented schemas; the `mp-` entry lists via
  `memory_pending.list_pending()`. `post_ref()` resolves `place/106`
  type+title through `_links.up`.
- Test comments deleted; synthetic queue files removed; state/digest kept as
  honest history.

## Finding (follow-up carded)

`comment_status` is **closed** on all board CPTs today — `place`, `trip`,
`ops-event` return `rest_comment_closed`; only `news`+`posts` accept comments.
Members can't yet comment on the routed types, and `memory-mirror` CPT doesn't
exist yet — the lanes are armed but see no traffic until comments are opened
WP-side → card `wp-board-cpt-comments-open` (KNB-0697).

## How to verify

- `systemctl --user list-timers wp-comment-sync.timer` on idc03 (armed, 15min).
- After merge+pull: post a comment on an open post, wait ≤15min (or run
  `python3 ~/CascadeProjects/chaba/scripts/ada/wp-comment-sync.py`), check
  `~/.local/share/wp-comment-sync/{state.json,digest.jsonl,record-corrections/}`,
  `~/.local/share/ada/memory-pending/mp-wpc*`, and the in-thread ack on the post.
