# Dispatch outcome — session-capture-c3-hooks (OPS-1356)

**Card:** `session-capture-c3-hooks` — "wire /session-capture and Devin session-end hooks to emit router events (dry-run first, then gated write)"
**Branch:** `dispatch/20261125-094719-goal-wire-session-capture-and-` @ `248fc960d8` (committed in worktree; not pushed, per dispatch rules)
**Date:** 2026-11-25

## What changed

**New emitter — `scripts/chaba/capture-event.py`** (executable, `--self-test` 10/10):
- Emits one normalized router event per call using the C.1 Capture Router Contract envelope (event_id, event_type, as_of, source, actor, subject, session, summary, refs/evidence, dedupe_key, volatility, sink_hint, payload, provenance).
- Appends to a runtime spool: `$CHABA_CAPTURE_OUT/events.jsonl` + `audit.jsonl` (default `~/.local/share/chaba/capture`, same dir as capture-ledger.yml). Never a canonical sink.
- Dry-run routes every event through `capture-router.py route()`; the proposal (target_sink/action/confidence/rule) is embedded as `event.route` and in the audit record.
- Deterministic `dedupe_key` (`{type}:{source}:{session|subject-anchor}:{slug}`, `--dedupe-key` override); re-emit = `{"status":"duplicate"}` noop+audit — replay-safe.
- Guards (all loud: stderr + exit 2 + metadata-only audit): type/source/volatility allowlists; `handoff` requires ≥1 `--ref` or `--where-filed`; `open_ask` requires `--open-ask`; secret-shaped content rejected BEFORE persistence (audit carries metadata only — rejected content is never written anywhere).
- No sink-write path exists in the emitter. Gated writes remain `capture-apply.py --key --apply --confirm` (OPS-0024) once C.2/C.4 bridge events→ledger.

**Wired surfaces:**
- `.opencode/commands/session-capture.md` — sweep step 7 emits the `handoff` event after the packet is saved.
- `.opencode/commands/handoff-packet.md` — step 4 emits `handoff`.
- `.opencode/instructions/session-capture.md` + `.opencode/skills/session-capture/SKILL.md` — same emit step.
- `.devin/skills/session-capture/SKILL.md` — sweep step 7 (`--source devin`).
- `.devin/skills/finish-and-close/SKILL.md` — step 7b emit line.
- `scripts/devin/session/devin-session-end.sh` — SessionEnd hook emits `focus_session` (reason, git-checkpoint msg, immediate-pin task/next/branch/open; open items ride as `--open-ask`, max 5 router-visible / 10 in payload). Nonzero emitter rc → stderr, non-fatal. Repo copy is source-of-truth; per-host `~/.config/devin/scripts/` deploy is a separate governed step.
- `ansible/playbooks/session-capture.yml` — `chaba-session-capture` helper gains `capture-event|router-event` passthrough; `session-end` also emits `focus_session` (`--source script`).

**Trail doc:** `docs/ssot/jobs/session-summary/2026-11-25-c3-router-event-hooks.yml`

## Acceptance check

- **No duplicate handoff packets:** only the capture step emits `type=handoff`, keyed per session+subject; identical re-emit verified → `duplicate` noop+audit, events.jsonl stays at 1 line. The hook emits `focus_session` (different type/key) and never claims a packet exists.
- **where_filed preserved:** `--where-filed "item -> sink"` strings stored verbatim in `payload.where_filed`; smoke test confirmed exact round-trip.
- **Failures loud:** guard rejections exit 2 with stderr + audit `rejected:*`; persist failures exit 3; route errors warn on stderr + audit `error` field while the event still lands; the hook prints `rc=` + stderr on emitter failure.
- **No fake events:** `handoff` without refs/where_filed is refused; `open_ask` without items refused; allowlists enforced; secrets rejected pre-write; the hook only emits the true lifecycle fact (`focus_session`).

## Verification

- `python3 scripts/chaba/capture-event.py --self-test` → 10/10
- `bash -n scripts/devin/session/devin-session-end.sh` + embedded-python compile → OK
- `yaml.safe_load ansible/playbooks/session-capture.yml` → OK
- Smoke (temp spool): handoff emit → route `evidence/skip` (already-filed pointer, not a create); replay → `duplicate`; focus_session with open asks → emitted.

## Notes / handoff

- C.1 contract lives on unmerged branch `ada/session-capture-c1-spec` (PR #218); envelope field names follow it. C.2 sibling dispatch (`20261125-094612`) was in flight — `events.jsonl` is the integration seam; if C.2's normalized router lands a different envelope, only `capture-event.py`'s emit mapping needs adjusting.
- `handoff` events dry-run-route to `evidence`/`skip` or `oc-note`/`skip` — correct: packets are already filed artifacts, so the router proposes pointers, never duplicate creates.
- Deploy note: hook script changes take effect on Devin hosts when `scripts/devin/session/devin-session-end.sh` is synced to `~/.config/devin/scripts/` (existing per-host mechanism; ansible playbook only checks presence, does not auto-patch hooks).

lessons:
- [session-capture-c3-hooks] capture-event.py emitter + spool design: events.jsonl/audit.jsonl under ~/.local/share/chaba/capture is the C.2/C.4 integration seam — keep envelopes contract-shaped so the normalized router can consume them unchanged.
- [session-capture-c3-hooks] Rejected-content guard must audit metadata only — writing the rejected payload to audit.jsonl would leak the secret the guard exists to catch.
- [session-capture-c3-hooks] SessionEnd hook can't know whether a handoff packet exists; emit only true lifecycle facts (focus_session) there and let the capture step own handoff events — that's what makes "no fake events" enforceable.
