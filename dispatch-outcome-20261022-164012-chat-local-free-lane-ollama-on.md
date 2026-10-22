# chat-local-free-lane — attempt 4 outcome

## What this run found (the real state, not the assumed state)

Attempts 1-3 built and merged the lane; this run did the production
verification and found the lane had **never served a real call** since
the 2026-10-16 adoption merge:

- `wp-news-digest` (hourly, idc03): every synthesis call timed out →
  silent gemini fallback on **every run for 6 days** (68 logged
  "chat-local synthesis unavailable" events).
- `wp-comment-sync` classify: timed out when it ran during a digest jam.
- `chaba-kanban-brief.service` (idc03): **killed at TimeoutStartSec=300
  on ~half its runs** — its 12 sequential `llm_why` calls × 30s timeout
  exceeded the budget while queued behind digest calls; the 2nd/3rd
  ExecStarts (`kanban-act.py`, `nest-overview.py`) starved with it.

## Root cause — physics, not wiring

- idc02 = 4 CPU cores; qwen2.5:7b evals ~20 tok/s. Digest payloads were
  ~3k tokens prompt + max_tokens 900 → **5-7min per call** (measured in
  idc02's ollama GIN log) vs caller timeouts of 90-120s.
- `OLLAMA_NUM_PARALLEL=1` — head-of-line blocking: a 30s classify or
  llm_why call queued behind a 6min synthesis always timed out.
- Ollama completes abandoned requests server-side, so each timed-out
  call still burned ~6min CPU — the jam outlasted every digest run by
  ~10min, exactly when the :30 kanban-brief run collided with it.

## What changed

### Code (branch dispatch/20261022-164012-chat-local-free-lane-ollama-on)

- `stacks/idc02/ollama/ollama.container` — `Environment=OLLAMA_NUM_PARALLEL=2`:
  short calls interleave with big syntheses instead of queueing.
- `scripts/ada/news-digest.py` — local-lane payload bounded to 8 items ×
  400-char text (was unbounded × 1200), `max_tokens` 900→600, timeout
  120→600s. Gemini fallback path unchanged (full payload, Thai intact).
- `scripts/ada/kanban-brief.py` — `llm_why` takes a monotonic deadline;
  per-render LLM budget `KANBAN_BRIEF_LLM_BUDGET`=100s so a jammed lane
  degrades to deterministic lines instead of starving the unit.
- `scripts/ada/wp-comment-sync.py` — classify timeout 30→90s.

### Config / SSOT

- `docs/ssot/infrastructure/ssot.llm-gateway.yml` — chat-local note +
  proof_lanes updated with throughput reality and new measurements.
- `docs/ssot/jobs/infrastructure/2026-10-22-chat-local-lane-throughput-tuning.yml`
  — new job doc (runbook + numbers).
- Fixed pre-existing YAML syntax errors in
  `docs/ssot/jobs/experiments/2026-10-20-ncm-thai-toy-train.yml`
  (same unquoted-`:` class as before — validator was red).

### Test-gate rot fixed (suite was red for every merge)

Two independent causes, both unmasked only after resolving the first:

- `test_tg_forward_provenance` — reported "drop diverged", but the real
  story was two-layer: (1) tony-omen's `~/CascadeProjects/ada-voice`
  checkout was stale (predates `b205457`, the base the drop was written
  on — pulled ff-only, it was clean); (2) against CURRENT upstream the
  patched `tg_relay.py` fails standalone-import because upstream added
  a `trivial_gate` sibling after the harness was written. Stubbed
  `trivial_gate` in `_load` — the provenance paths never reach the gate
  (voice turns only).
- `test_cpt_post_drop` — the drop already MERGED upstream (reverse-apply
  clean) but the test still demanded bare forward `git apply` — the one
  drop-test file attempt 3's tri-state migration missed. Migrated to
  `check_patch`/`drop_guard_ok` + depth-1 `file://` clone like the
  others.

### Live side effects

- idc02: quadlet updated + `systemctl --user restart ollama` — verified
  `OLLAMA_NUM_PARALLEL:2` in server config, `active`, models intact,
  still bound to tailnet IP only (public :11434 refused).
- No litellm or caller-unit changes needed live — script fixes ride the
  normal merge → served-checkout sync.

## Verified

- Gateway smoke `chat-local` via CHABA key: `LANE_OK`, HTTP 200, 2.1s.
- Concurrency proof through the gateway (the actual fix): synthesis-size
  call + classify-size call simultaneously → small returned in **81.6s**
  (previously: guaranteed timeout), big returned in **263.4s** inside the
  new 600s budget (previously: 120s timeout at ~60% progress).
- `python3 -m py_compile` on all three scripts.
- `pytest tests -x -q` → **434 passed, 38 skipped, 117s** against a
  current ada-voice checkout (was 1 failed: tg-forward-provenance; then
  1 failed: cpt_post — both environmental/harness rot, both fixed).
- `ssot-validate-all.mjs` — 0 errors after fixes (was 2, one mine in the
  new job doc + one pre-existing).

## Watch after merge

- Next `wp-news-digest` hourly runs: absence of "chat-local synthesis
  unavailable" in the journal = lane serving.
- `chaba-kanban-brief` should stop hitting TimeoutStartSec.
- If qwen7b still can't keep up: next levers are a 3B model for bulk
  synthesis or a GPU host — card scope kept it on idc02.

## Card state

Still `backlog` per the YAML; left a board comment with findings. The
card's remaining question for Tony is whether ~4min/call synthesis on
the free lane is acceptable vs a paid-gemini `summary` alias — my take:
yes, it's hourly batch work.
