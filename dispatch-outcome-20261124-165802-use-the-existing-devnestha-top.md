# Dispatch outcome — kk-video-devnest-topic-event-feed (OPS-0927)

Commit: `e4bf0d6096` on `dispatch/20261124-165802-use-the-existing-devnestha-top`

## What changed

- `scripts/board/publication.py` — `TelegramSink` now renders concise artifact
  context (`refs:` from `evidence[]`/`media[]`, plus allowlisted
  `job_status|qc|sha256|hash|artifact|drive` meta) and, when
  `meta.tg_thread_id` is absent, forwards `project_id`, `card_ref`, and
  `job_ref` to the relay `/send` door. Explicit `tg_thread_id` still wins.
- `scripts/devnest/devnest-tg-relay.py` — `_find_project_topic` reconciles
  project manifests before lookup and can resolve a project-prefixed
  `job_ref` (e.g. `kk-video-c9f99fee6146-preview`) to the bound project
  topic. `route_send` keeps explicit `message_thread_id` first, fails closed
  for unbound explicit project/card refs, and preserves legacy General
  behavior only for unmatched non-project job refs. `milestone=true` /
  `mirror=general` remains the only General mirror.
- `tests/board/test_publication.py` — added coverage for project/card/job
  ref forwarding, explicit-thread override, and artifact/QC rendering.
- `tests/test_devnest_tg_relay.py` — added coverage for `job_ref` topic
  routing, unmatched-job General fallback, and manifest reconcile lookup.
- `docs/kb/board-api-write-door.md` — documented the Telegram ref-routing
  contract and the artifact/QC meta fields producers should use.
- `docs/ssot/jobs/devnest/2026-11-24-kk-video-devnest-topic-event-feed.yml`
  — job trail for the binding/routing decision and verification.

## Result

The publication path can now route Sacred Father (`kk-video-c9f99fee6146`)
project events to the existing DevNestHA thread 33 through the relay's
manifest-backed project binding instead of relying on a hard-coded thread
id or silently falling back to General. Intake/source-received handling in
the relay already binds inside the project topic; artifact milestones and
meaningful job-status events now have a supported PublicationEvent →
TelegramSink → relay route. No Telegram test message was posted and no
sharing permissions were changed.

## Verification

- `python3 -m py_compile scripts/board/publication.py scripts/devnest/devnest-tg-relay.py` — ok
- `python3 -m unittest tests.board.test_publication -v` — 75/75 ok
- `uv run --with pytest python -m pytest tests/test_devnest_tg_relay.py -q` — 58/58 ok
- `python3 scripts/board/board-api.py --selftest` — ok
- Mocked end-to-end: `PublicationEvent` → `TelegramSink` → `relay.route_send`
  → captured `_send_text` resolved `thread_id=33`; no Telegram API call.
- Live read-only check: board-api `/health` ok; `POST /publish {op:sinks}`
  returned 11 registered sinks including `telegram`. Relay `:8919` is
  loopback-only on idc03 and not reachable over tailnet from this host, so
  relay verification was code/mocked plus the prior OPS-0927 live binding
  record on the card.

## Deploy note

This is committed on the dispatch branch only. After the normal merge, the
served idc03 checkout picks up `publication.py`/`board-api` through the
usual sync path, and `devnest-tg-relay.service` needs the normal service
restart for the relay-side `job_ref`/reconcile change.

lessons:
- `PublicationEvent.card` must be a lowercase slug; `OPS-####` refs belong in relay `card_ref`/meta paths, not the canonical `card` field.
- `devnest-tg-relay` `/send`/`/health` is loopback-only on idc03; tailnet `:8919` is not a verification surface — use mocked `route_send` or board-api `/publish {op:sinks}`.
- SSOT commits run `ssot-optimize` → `dev-system-assess --metrics-only`, which can dirty `docs/ssot/ssot.dev-system.assessment.yml`; restore unrelated generated diffs before close-out.
- System python lacks pytest; use `uv run --with pytest python -m pytest tests/test_devnest_tg_relay.py -q` for the relay suite.
