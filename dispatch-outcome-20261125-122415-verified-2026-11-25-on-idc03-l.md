# Dispatch outcome — telegram-topic-binding-publish-outbox (OPS-1386)

## What was wrong

Commit `e4bf0d6` (2026-11-24, kk-video-devnest-topic-event-feed) made
`TelegramSink` forward `project`/`card`/`job` refs to the devnest-tg-relay
`/send` door. The relay resolves explicit refs only through active
project-topic bindings (manifest-backed registry) and fails closed with
404 — by design, "never a silent post to General". But the lifecycle
producers (`runner-agent._publish`, `waiting_cards.publish` via
`notify_lifecycle` → kanban-dispatch + merge-sweep) emit `{card: <id>}`
with **no project ref**, so every card-verified milestone started
404ing into the publish outbox: 9 retrying + 24 dead-lettered on
2026-11-25, all `sink=telegram`. `project=chaba` (unattended digest) and
`project=education` (trade-docs news) failed the same way — no manifests
existed for either project.

## What I did (live, on idc03)

1. Created two forum topics in DevNestHA via `createForumTopic`:
   - thread **100** `PRJ chaba — board ops`
   - thread **101** `PRJ education — lessons`
2. Wrote `~/.local/share/devnest/projects/{chaba,education}/project.json`
   manifests with `topic{thread_id,…,status:active}`; the relay's
   `_reconcile_topics` registered both (topics.json now 33/100/101).
3. Re-backed-up state to `/tmp/opencode/board-api-publish-backup-20261125-devin/`,
   patched `outbox.jsonl` + `dead.jsonl`: empty `project` → `chaba`
   (all were chaba-board lifecycle events), dead entries requeued into
   outbox with `attempts=0, next_at=0`; `dead.jsonl` kept as history.
4. `POST /publish {op:drain}` → **33 delivered, 0 retrying, 0 dead,
   0 pending**. Receipts `tg:100`/`tg:101`; relay logged `/send` 200s.
   `outbox.jsonl` now empty.
5. Verified end-to-end: fresh `/publish` milestone with
   `project=chaba, card=telegram-topic-binding-publish-outbox` →
   `telegram=delivered ref=tg:100` (also wrote a board comm on the card).

## What I changed (worktree, commit e46eb5847b)

- `scripts/board/waiting_cards.py` `publish()`: event gains
  `"project": "chaba"`.
- `scripts/board/runner-agent.py` `_publish()`: same (runner-agent is
  standalone, can't import waiting_cards).
- `tests/board/test_waiting_cards.py`: new
  `test_publish_tags_chaba_project` locks the contract — 27/27 pass.
- `docs/kb/board-api-write-door.md`: documented the binding runbook.
- `docs/ssot/jobs/devnest/2026-11-25-telegram-topic-bindings.yml`: trail.

Side benefit: `topic_key` collapses to `chaba`, so the telegram 10-min
noise floor now actually throttles lifecycle spam (previously each card
was its own topic → zero dedup).

## Caveats / residual

- Until the producer fix merges and runner tooling syncs to hosts, NEW
  card-only lifecycle events will still 404 → outbox → dead-letter (the
  designed alarm). Volume is a few/day; the backlog is clean now.
- Any future producer emitting unbound `project=`/`card=` refs hits the
  same wall — fix = bind a `PRJ <id> — <title>` topic + manifest (runbook
  now in board-api-write-door.md).
- The two new Telegram topics are permanent by policy (no delete); the
  33 drained notifications are real messages in `PRJ chaba — board ops`
  / `PRJ education — lessons`.

## How to verify

- `ssh idc03 'wc -l ~/.local/state/board-api-publish/outbox.jsonl'` → 0
- `curl -s http://127.0.0.1:8919/health` on idc03 → `"topics": 3`
- Check the DevNestHA Telegram group: threads 100/101 hold the backlog.
- `python3 -m unittest tests.board.test_waiting_cards` → 27/27.

lessons:
- e4bf0d6's fail-closed ref forwarding silently broke every card-scoped
  lifecycle producer — grep all /publish callers for bare `card=` refs
  when changing relay routing semantics.
- "Bind a topic" for ~20 distinct card ids is impossible (one card per
  project entry); the right unit is the board project — tag events
  `project=chaba`, let the per-topic noise floor dedupe.
- Dead-lettered outbox entries can be deliberately requeued by appending
  patched copies to outbox.jsonl (attempts=0, next_at=0) — dead.jsonl is
  history, not a retry queue; back up first.
- createForumTopic + a project.json manifest is the whole binding
  ceremony; the relay self-registers via _reconcile_topics — no restart
  or code deploy needed for new project topics.
