# Dispatch outcome — devnest-publication-adapter-layer (OPS-0913)

## What was asked
Design a provider-neutral DevNest publication layer: canonical
PublicationEvent, a board-api `/publish` adapter door, the existing
/job /lesson /report /comment endpoints preserved as compatibility
adapters, idempotency + outbox/retry, sink capability checks, rate/noise
policy, private-first visibility, evidence requirement for news, tests
with a mock sink, and proof that WP is only one adapter (a second sink
receives the same event).

## What changed (this worktree — not pushed, not deployed)

- `scripts/board/publication.py` (NEW, ~570 lines) — the whole layer,
  standalone/pure (board-api injects providers; tests inject mocks):
  - `validate_event` — canonical PublicationEvent: `kind`
    (progress|milestone|report|lesson|news|alert), `title`, `source`,
    `body`, `project`/`job`/`card`/`parent` refs, `evidence[]`,
    `confidence` (observed|measured|verified), `visibility`
    (private|members|public, **private-first default**), `audience[]`,
    `media[]`, `occurred_at`, `event_id`, `idempotency_key`
    (deterministic derivation when absent — identical logical events
    dedupe), `sinks[]`, `force`, `meta{}` provider extras.
  - Validation gates: body required for lesson/report/news; **evidence
    required for news**; **public news requires confidence=verified**.
  - `Sink`/`FuncSink`/`JsonSink`/`TelegramSink` — capability checks per
    sink: `surface` class, accepted kinds, `evidence_required`.
    Eligibility = `rank(event.visibility) >= rank(sink.surface)`:
    private events only reach private surfaces (board comms, json
    ledger); members adds WP-private posts + Telegram; public adds
    publish-status surfaces.
  - `DEFAULT_ROUTES` — progress→job+board (heartbeat-class: throttled,
    never Telegram); milestone→job+board+TG; report→report+board;
    lesson→lesson; news→news+board+TG; alert→TG+board+job.
  - `NoisePolicy` — progress 15 min per (sink,topic), Telegram 10
    min/topic floor on any kind, identical alerts deduped 60s;
    `force:true` bypasses noise only, never visibility. *Do not publish
    every heartbeat* is enforced in code.
  - `Outbox` — `delivered.json` idempotency store, `events.jsonl`
    ledger, `outbox.jsonl` retry queue (30s·2ⁿ ≤30m, dead-letter after
    5), `drain()` piggybacked on every publish plus an `op:"drain"` op.
  - `publish_event` — validate → sink-name check → dedupe → route →
    per-sink receipts (`delivered|queued|skipped|suppressed` + reasons).

- `scripts/board/board-api.py` — `POST /publish` on the remote-write
  path (WP_LOCK; daemon-name `from` allowed like `/job`). Sink registry
  `_pub_sinks`: `job`/`lesson`/`report` adapters call the SAME
  `do_job`/`do_lesson`/`do_report` functions the compat endpoints use;
  `news` adapter upserts the WP `news` CPT by `pub-<event_id>` slug
  (evidence embedded in content; members→private post, public→publish);
  `board` adapter appends `pub <kind>: <title> [evt-…]` comms
  (operational audit, nested WP_LOCK→LOCK order — documented);
  `telegram` adapter posts concise `[DevNest <kind>]` text to the
  devnest-tg-relay `/send` door; `json` adapter appends the canonical
  event to `published.jsonl`. `op:"sinks"` returns the capability
  table. `JOB_META_KEYS` gained `event_id` for traceability. Selftest
  extended with a `/publish` block.

- `tests/board/test_publication.py` (NEW, 29 tests) — schema,
  routing, visibility gating, mock-sink parity (**same canonical event
  reaches a WP-like adapter and a JsonSink byte-identical**),
  idempotent dedupe, outbox queue/drain/dead-letter, noise throttling,
  Telegram render/floor, and board-api wiring with faked `wp_api`.

- Docs: `docs/kb/board-api-write-door.md` (/publish row + full
  section), `docs/ssot/ssot.procedures.yml` board-write entry,
  `AGENTS.md` publication-layer bullet, and the trail record
  `docs/ssot/jobs/devnest/2026-10-26-publication-adapter-layer.yml`.

## Key design decisions
- **Compat adapters are literal**: the legacy endpoints keep their
  bodies/handlers; `/publish` calls the same writer functions — one
  provider implementation, not two. WP provably is only one adapter.
- **Visibility gates by sink surface class**, not per-sink config:
  private-first means members/public surfaces are opt-in per event.
- **Receipts never lie**: partial fan-out returns 200 with per-sink
  status (a queued Telegram does not fail a delivered nest_job);
  validation/auth errors stay 400/403.
- **Provider-level idempotency too**: news posts upsert by
  `pub-<event_id>` slug, so an outbox retry after a timed-out POST
  can't double-publish.
- State is off-repo on the service host (`$BOARD_API_PUB_STATE`,
  default `~/.local/state/board-api-publish/`), env-tunable thresholds.

## Verification
- `python3 -m unittest board.test_publication` → 29/29 OK.
- `python3 -m unittest discover -s board` → 234/234 OK (6 skipped).
- `python3 scripts/board/board-api.py --selftest` → ok, incl. wp+json
  parity, dedupe, visibility skip, unknown-sink 400, telegram outbox.
- Deploy path: normal served-checkout sync + `chaba-board-api` restart
  on idc03 — no WP plugin bump needed (all touched CPTs already exist).
  Smoke after merge: `POST /publish {"op":"sinks"}`.

## Result
Done — the layer is implemented and fully test-verified in the
worktree; merge/deploy is the runner closeout's job.
