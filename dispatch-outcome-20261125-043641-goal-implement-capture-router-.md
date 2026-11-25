# Dispatch outcome — session-capture-c2-router (OPS-1354)

**Card:** `session-capture-c2-router` — "implement capture-router CLI/lib:
normalize+route+dedupe+audit, --dry-run default for new sinks"
**Branch:** `dispatch/20261125-043641-goal-implement-capture-router-` @ `600804b8d9`
(committed in worktree; not pushed, per dispatch rules)
**Date:** 2026-11-25

## What was found

The C.1 contract (merged into `docs/ssot/ssot.knowledge-capture.yml`) defines a
candidate→proposal pipeline, and three siblings already landed pieces:

- `scripts/chaba/capture-router.py` — OPS-0016 read-only proposal classifier
  (`route()` lib + `--text/--input` CLI). No event consumer.
- `scripts/chaba/capture-event.py` (C.3, merged) — emits C.1-contract events to
  `$CHABA_CAPTURE_OUT/events.jsonl` + `audit.jsonl`.
- `scripts/chaba/capture-harvest.py` (C.4, merged) — bounded scan emitting
  normalized events to `reports/session-capture/events.jsonl`.

The missing C.2 piece was the **consumer**: nothing turned those normalized
events into routed, deduped, audited proposals. That is what this change adds.

## What changed

**`scripts/chaba/capture-router.py`** — gained an events mode alongside the
unchanged propose mode (`route()` stays pure; `harvester.py` and
`capture-event.py` imports unaffected):

- `--events`/`--events-dir` consume events.jsonl files; with no flags and no
  `--text/--input`, bare invocation consumes the default spool paths
  (`$CHABA_CAPTURE_OUT/events.jsonl`, `reports/session-capture/events.jsonl`).
- `event_to_candidate()` normalizes the C.1 envelope (summary + refs +
  evidence + `payload.where_filed`/`open_asks` → text; `source_id` falls back
  to event `dedupe_key`; filed event types → `already_filed`).
- `consume_events()` routes each event through `route()`, then dedupes at
  three layers: event `dedupe_key` in `router-state.json`, a within-run seen
  set, and router `dedupe_key` vs state + ledger entries.
- Audit: append-only `router-audit.jsonl` — run-start/per-event/run-done
  records, every one `dry_run=true`, `sink_write="none"`, and the approved
  pair gets an `apply_path` hint (`capture-apply.py --key … --apply
  --confirm …`). Rejections audit metadata only.
- New proposals append to `router-proposals.jsonl` and upsert into
  `capture-ledger.yml` entries (atomic write, `applied:` block preserved) —
  the bridge that lets `capture-apply.py` pick up `kanban/create` keys.
- Guards: missing `dedupe_key` → rejected; bad JSON lines counted and skipped;
  secret-shaped content re-scanned via `capture-event._scan_secrets` and
  rejected without persisting content; `--since`/`--limit` bounds.
- There is deliberately **no `--apply` and no network code** — dry-run is the
  only posture; the sole write door stays `capture-apply.py` → board-api.

**`tests/test_capture_router_events.py`** — 5 pytest cases: route+audit shape,
idempotent rerun (noop+audit), no writes outside the runtime dir, secret
rejection, bad-envelope handling.

**`docs/ssot/jobs/session-summary/2026-11-25-c2-capture-router-events.yml`** —
job record; **`docs/ssot/CHANGELOG.md`** — 2026-11-25 entry.

## Acceptance check

- **Idempotent unit tests:** `pytest tests/test_capture_router_events.py` →
  5/5 (venv; host python lacks pytest); `--self-test` → propose 13/13 + events
  6/6. CLI smoke: 2-event spool → 2 proposals + 2 ledger entries; rerun →
  `new=0 duplicate=2 proposals_new=0 ledger_added=0`.
- **Audit JSONL:** `router-audit.jsonl` verified — run + per-event records
  with `dry_run=true`, `dedupe_status`, `target_sink`, `router_dedupe_key`.
- **No unapproved sink writes:** events mode has no sink-write code path;
  pytest asserts the only files created are the three runtime artifacts.
- **Board-api mutation door:** zero network calls; `kanban/create` proposals
  land in the ledger as candidates only — `capture-apply.py` gates unchanged.

## Verification run

- `python3 scripts/chaba/capture-router.py --self-test` → 13/13 + 6/6
- `python3 -m pytest tests/test_capture_router_events.py -q` → 5/5
- `capture-event.py --self-test` → 10/10, `harvester.py --self-test` → 5/5
  (no regressions)
- `node scripts/ssot-validate-all.mjs` → 6474 files, 0 errors
- SSOT pre-commit validation passed on commit

## Notes / handoff

- Who runs `consume_events` periodically is a separate ops decision — the
  daily `chaba-capture-harvest` job on idc02 is the natural host; not wired
  here.
- Event sources outside the OPS-0016 scanner set (devin/opencode/script/
  manual/check) route through the same rules; non-focus-inbox
  `kanban/create` proposals will be refused by capture-apply's source gate —
  recorded as proposals, never improvised into writes.

lessons:
- [session-capture-c2-router] capture-router.py was already the OPS-0016 proposal lib — C.2 needed the events.jsonl CONSUMER, not a new classifier; extending the same file keeps one router per the C.1 contract.
- [session-capture-c2-router] Plain YAML list items can't contain ": " — job-record bullets like "CLI smoke: ..." need quoting or ssot-validate fails with a confusing scanner error two screens down.
- [session-capture-c2-router] pytest isn't installed on mn01 — verify pytest files in a throwaway venv (/tmp/c2venv) and rely on --self-test for host-portable checks.
