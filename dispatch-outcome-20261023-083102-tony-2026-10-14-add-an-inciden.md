# Dispatch outcome — wp-activity-cpt-timeline-links (2026-10-23)

Built the full activity-CPT pipeline per Tony's 2026-10-14 spec. All three
board requests were already answered with the starred defaults — CPT name
`activity` (status field marks incidents), emitters = renders + translate
only, visibility = per-lane private — so implementation proceeded on those.

## Changed

- `integrations/wp-boards/chaba-boards.php` → **v0.8.0**. New `activity`
  CPT: hierarchical (parent = session/turn `kind=session`, children = one
  per tool call `kind=tool`), `has_archive` (/wp/activity/), private-status
  member gating like /chat/line/*. REST meta: kind/tool/lane/status
  (ok|failed|blocked)/model/cost_usd/artifact_url/ref_url/prompt_excerpt/
  session_id/chat_id/duration_s/event_id/occurred_at/error (error keeps raw
  JSON like ops_error.raw_result). Admin list: artifact thumb column,
  colored status badge, occurred_at-desc default sort. Single view: status
  badge + artifact media + prompt blockquote + params table + error
  details; session parents list their children. New
  `[chaba_activity lane= status= limit=]` feed shortcode for per-lane
  private pages.
- `scripts/ada/activity-posts.py` (new) — the writer. **Journald sweep,
  not an ada-voice hook**: joins `function_call received`/`result` pairs
  per lane unit (ada-kk/ada-ha-tony/ada-michael on idc03) for the emitters
  allowlist (default regex: ada_render_image|ada_render_video|page_snapshot|
  *translat*|*vision*; `ACTIVITY_TOOLS` env overrides). Resolved pairs →
  ok|failed children under a slug-upserted session parent whose status
  escalates to the worst child. A `received` with no `result` for >15min →
  **status=blocked** — that's the killed/refused-mid-turn evidence the card
  wants (pending calls persist in the state file across script restarts).
  Dedup via deterministic slug `act-<md5>` + `?slug=` lookup — idempotent.
  Flags: --dry-run/--since/--session/--lane/--journal-file/--selftest.
- `scripts/ada/line-chat-timeline.py` — dedupe: fetches recent activity
  posts once per run (≤500), maps artifact_url→permalink and event_id→
  permalink; a journal media row matching either renders `🔧 <a>Activity —
  …</a>` instead of re-uploading + re-inlining the media. WP outage
  degrades to empty maps — the timeline never wedges.
- `docs/ssot/infrastructure/ssot.jobs.yml` — new job `activity-posts`
  (idc03, every 15m, condition_path-gated); rendered units in
  `systemd/generated/idc03/activity-posts.{service,timer}`.
- `docs/ssot/apps/ssot.wp-boards.yml` — v0.8.0 changelog, activity
  post_type, title standard, writer entry, timeline dedupe note.
- `docs/ssot/jobs/ada/2026-10-23-activity-cpt-timeline-links.yml` — design
  + mechanics trail (writer-choice rationale, field extraction, dedup,
  deploy steps, followups incl. the KNB-0657 media_receipt fold-in).
- `integrations/wp-boards/dist/chaba-boards-0.8.0.zip` — deployable plugin
  zip (chaba-boards.php + usage-pull-cron.php; the 0.6.0 zip had missed the
  cron shim).

## Verified

- `php -l` clean; `python3 -m py_compile` clean on both scripts.
- `activity-posts.py --selftest` passes (ok / failed / allowlist-skip /
  pending→blocked paths); `--journal-file --dry-run` prints the would-post.
- `render-jobs.py --check` (73 jobs OK) + `--host idc03` render clean.
- `ssot-validate-all.mjs`: new/edited files Valid; the 7 errors are all
  pre-existing files unrelated to this change.

## Not done (gate)

- **Plugin deploy is a prod change needing Tony's approval** — zip staged;
  run `scripts/wp-boards/deploy-plugin-zip.sh integrations/wp-boards/dist/
  chaba-boards-0.8.0.zip` on tony-omen when approved. Until it lands the
  writer's POSTs 404 and its cursor holds — no events lost.
- Merge to master is left to the normal dispatch merge flow; the idc03
  timer self-arms via condition_path once the script lands in the served
  checkout.

## How to verify live (post-deploy)

1. `/wp/v2/types` lists `activity`; `/wp/activity/` archive resolves.
2. `activity-posts.py --since "6 hours ago" --dry-run` on idc03 shows
   would-post rows; real run returns 201s; children nest under
   `act-s-<lane>-<sid>` parents in wp-admin.
3. Next `line-chat-timeline.py` run: a journal row whose url matches an
   artifact_url renders the 🔧 link in the lane timeline_block.
