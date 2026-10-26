# Dispatch outcome — devnest-topic-project-routing (OPS-0915, 2026-10-26)

Card: `devnest-topic-project-routing` — durable topic registry for
TG/DevNestHA so forum topics become the human collaboration surface while
board cards + project manifests stay the source of truth.

## What changed

`scripts/devnest/devnest-tg-relay.py` (capture relay + command router +
PDF intake on idc03):

- **Durable registry** `STATE_DIR/topics.json` (atomic tmp+replace):
  `message_thread_id -> {kind, name, lane, visibility, project_id,
  card_ref, card_id, status, ...}`. Entries are never deleted; rollback
  sets `status: rolled_back`. On a miss the relay reconciles from project
  manifests (`topic.thread_id`), so a lost/corrupt registry self-heals;
  `main()` reconciles at startup and `/health` reports binding count.
- **Permanent topics** General/Inbox/Control/Ops/Research/Education/
  Archive with fixed lanes+visibility; **project topics** follow
  `PRJ <project-id> — <short title>` (≤128 chars). `forum_topic_created`
  /`edited`/`closed`/`reopened` service messages register/classify names
  — the only place names are parsed; ordinary-message identity is always
  the bound thread_id, never the display title. Renaming an existing
  topic registers it (ops path for pre-existing topics).
- **Quarantine**: messages in unregistered/quarantined/closed/rolled-back
  threads are recorded with `topic_status`, get a one-time policy notice,
  and never reach commands, intake, or the capture-ack.
- **PDF intake**: General/permanent-topic PDFs keep the existing
  download→card flow, then `createForumTopic` makes the `PRJ …` topic;
  binding writes the registry entry, `manifest.topic{thread_id,...}`, and
  a board `/comment` (`from: devnest-tg`). Origin topic gets a handoff
  ack; the PRJ topic gets a "project open" note. If `createForumTopic`
  fails, intake still stands and the reply carries the exact manual
  topic name — `forum_topic_created` completes the bind later.
  PDFs inside a bound project thread attach to that project
  (manifest `sources[]`, sha-deduped) — no new card/topic.
- **`/send` routing**: `{project_id}`/`{card_ref|card_id}` resolves the
  bound thread; unbound → LookupError → HTTP 404, never a silent post to
  General. `milestone=true` (or `mirror:"general"`) additionally mirrors
  to General — the only mirroring path.
- **`deleteForumTopic` is hard-blocked** in `_api`
  (FORBIDDEN_API_METHODS) — topics are never deleted.
- Hardening: conversation files now use `_safe_filename(topic)` (topic
  names can't path-traverse); `milestone` parsing tightened.
  `message_thread_id == 1` normalizes to General.

`tests/test_devnest_tg_relay.py` — 40 tests (was 21): topic-aware
registration (permanent/PRJ/quarantine/edit-promote), unknown-thread
quarantine-once, Inbox→PRJ handoff with real download path, same-topic
PDF attach, manual-instruction fallback + manual bind completion,
project/card send routing, milestone mirror, unbound-send refusal,
registry reload + manifest reconcile, rollback/never-delete.

`docs/ssot/jobs/devnest/2026-10-26-tg-topic-registry.yml` — job doc:
registry schema, registration paths, quarantine policy, intake flow,
/send contract, invariants, deploy note.

## Verification

- `pytest tests/test_devnest_tg_relay.py` — 40/40 pass (in a worktree
  venv; host python has no pytest).
- `python3 -m py_compile` clean on relay + tests.
- Job doc parses as YAML.

## Deploy / live gate (not done — dispatch can't push/deploy)

Same path as OPS-0911/OPS-0912: merge → sync idc03 exec checkout →
`systemctl --user restart devnest-tg-relay.service`. Live check: create
the permanent topics (or rename to fire `forum_topic_edited`), then
resend the KK PDF in Inbox → expect `PRJ kk-video-*` topic, manifest
`topic.thread_id`, card bind comment, and `INTAKE attached` on a second
PDF posted inside the PRJ topic.

## Behavioral note

Commands/intake in a thread the registry doesn't know are now quarantined
(recorded + one notice, no action) — previously they ran. That's the
card's "unknown topics are quarantined" rule; register via
forum_topic_created/rename or seed `topics.json`.
