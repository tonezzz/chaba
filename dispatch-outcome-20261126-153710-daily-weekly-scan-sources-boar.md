# Dispatch outcome — devnest-news-watch-procedure (weekly scan)

Date: 2026-11-26 · Host: con01 · Worktree: dispatch-wt-20261126-153710-daily-weekly-scan-sources-boar

## What changed

- **New procedure doc** `docs/kb/devnest-news-watch-procedure.md` — the
  deliverable that had been missing since the card's first dispatch
  (2026-10-27 died on the push-cred gap; triage 2026-11-26 confirmed "no
  procedure doc on master"). Defines cadence, scan sources, the six
  newsworthy triggers, the item contract (evidence/date/impact/
  before-after/confidence/next-step), story threading via stable
  `event_id` → WP slug upsert, `/publish` mechanics, private-first
  visibility, and consumer-proof verification.
- **Scan record** `docs/ssot/jobs/devnest/2026-11-26-news-watch-first-scan.yml`
  — sources scanned, 4 items published, gate-rejected candidates with
  reasons, receipts, follow-ups.
- **Published 4 news stories** via board-api `/publish`
  (`kind=news`, `visibility=members`, private-first):
  - `evt-nw-nestmgr-v2-actuation-20261126` — nest-mgr v2 guarded actuation
    live on idc02/con01/mn01 (Tony-approved 15:24 +07). WP news post 7907.
  - `evt-nw-ha-auth-watch-loopfix-20261126` — ha-auth-watch crash loop
    root-caused: non-writer commit path + dedupe state eviction +
    false-positive sweep alerts; verified live ticks. WP post 7905.
  - `evt-nw-model-efficiency-20261124` — DeepSeek V4.1 Flash cheap/fast via
    OpenRouter; :free lanes quota-dead; laguna delisted; qwen3:4b
    empty-content trap. WP post 7906.
  - `evt-nw-bench-recall-postprune-20261124` — hybrid recall hit@3 91.7%
    reproduced on post-prune archive corpus. WP post 7908.
- Receipts: news CPT `created` ×4 (wp_status private = members surface),
  board comms delivered ×4, wiki sinks skipped by design, telegram 1
  suppressed (600s floor) + 3 queued→relay 404 "no active topic bound for
  project=devnest card=<ref>" — outbox retries then dead-letters; fix is a
  devnest project topic binding (flagged as follow-up, not a resend).

## Gate-rejected (scanned, not newsworthy)

colibri-bench pack (prep done, benchmark not yet run — watch), ada-dev-2
cap raise (ops hygiene), gemini-dev-capabilities (already on Education
surface), runner-drift/merge-sweep churn, ha-auth token audit (folded into
the loopfix story).

## How to verify

- `docs/kb/devnest-news-watch-procedure.md` and the job yml above.
- Board-api: `POST /publish {"op":"drain","from":"devin"}` shows pending
  telegram retries; WP news slugs `pub-nw-*` exist as private posts.
- Card comms on `devnest-news-watch-procedure` record the run.

## Notes

- Worktree-only per dispatch rules: no push, no deploy. The two new files
  ride the dispatch branch for merge-sweep.
- `.dispatch-scratch/newswatch/` event JSONs were removed after publish.

lessons:
- `/publish` requires a top-level `"from"` actor field separate from the event's `source` — omitting it returns "from must be an actor or a host/daemon name" before validation.
- WP news slug derives from `event_id` (`pub-` + event_id minus `evt-`): reuse the same event_id to update a story in place; that is the clustering/threading mechanism — there is no separate parent field for news CPT.
- Telegram sink refuses card-scoped events when `project` is set but no topic binding exists for that card — it queues then dead-letters; dropping `project` would route to General instead.
- YAML job records: plain scalars containing `: ` or leading `{` break safe_load — quote list items with colons/braces.
- git log on this repo is ~95% board-api comment/action noise; filter `board-api (comment|action|inbox|card|publish)|board: live card|Merge|checkpoint` before reading substance.
