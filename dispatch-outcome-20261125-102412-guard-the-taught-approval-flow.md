# Dispatch outcome — ada-dispatch-approval-scenario (attempt 2)

## What was built

A live smoke-tier scenario guarding Ada's taught OpenCode approval
handshake (ada-voice d27be7c / tool_guide.yml), plus the harness and
board-side pieces it needs.

### ada-voice worktree — branch `dispatch/20261125-102412-guard-the-taught-approval-flow`, commit `527eaca`

- `tests/scenarios-live/ada_opencode_approval.yaml` — 4-turn scenario,
  `transport: text`, `tier: smoke`, `needs_tools:
  [ada_opencode, ada_opencode_dispatch, kanban]`:
  1. User asks Ada to preflight `ada-opencode-approval-probe` and raise
     the board ask — asserts `ada_opencode` called with `preflight` AND
     `kanban` called with `dispatch` wording.
  2. `board_respond:` driver turn posts Tony's "yes" via `/respond`.
  3. User says the answer landed — asserts `ada_opencode_dispatch`
     called with `confirmed` arg and result contains `"queued": true`.
  4. Status readback — asserts `kanban` or `ada_opencode` called.
- `scripts/scenario-live.py` — new `board_respond:` driver turn
  (`_board_respond()` + elif branch + docstring). respond is
  owner-only for Ada, so the driver plays Tony's board click as
  `from: tony` against `$ADA_BOARD_API_URL` (default Caddy board-api
  route). Picks the newest open `requests[]` entry; falls back to
  re-answering the newest via `reopen` so repeat smoke runs complete
  after board-api's duplicate-request-id refusal. Polls ~30s for the
  ask to settle.
- `tests/benchmark.yml` — scenario added to `write_allowed_in` (it
  legitimately writes via kanban + ada_opencode_dispatch).
- `backend/tool_guide.yml` — the `ada_opencode`/`ada_opencode_dispatch`
  entries now teach RE-PREFLIGHT: every card write (ask, respond,
  comment, move) bumps `card.updated` and re-keys the
  `approval_receipt`, so the pre-ask triple is stale; on
  `approval_receipt_mismatch` replay the FRESH triple, never retry the
  stale one.

### chaba worktree — branch `dispatch/20261125-102412-guard-the-taught-approval-flow`, commit `74712995cb`

- `docs/ssot/kanban/cards/ada-opencode-approval-probe.yml` — dedicated
  canary card the scenario targets. Fully staged S3 `lane_envelope`
  (required by runner-agent staged admission for `executor: opencode`
  claims on idc02), `ops-readonly` profile,
  `litellm/or-free-nemotron-ultra` (free tier → $0/run),
  `task_class: read_only`, `llm_key_alias: chaba` (board-api
  allowlist), `max_usd: 0.05` + `max_turns/max_tokens/max_wall_time_s/
  max_retries` as action fields so `ada_opencode` preflight passes
  without Ada supplying args, `held_out_py` verifier, artifact under
  `evals/opencode-lane/out/`.
- `docs/ssot/jobs/ada/2026-11-25-dispatch-approval-scenario.yml` —
  jobs trail recording the contract findings.

## Key contract findings (why the probe card is shaped this way)

- idc02's runner requires `action.lane_envelope` satisfying
  `prepare_profile_dispatch` + `check_envelope` vs
  `evals/opencode-lane/profiles/ops-readonly/profile.yml` — a bare
  executor+prompt card is NOT claimable.
- `ada_opencode` preflight reads budget/limits from `action.max_*`
  card fields when present.
- board-api `/respond` is owner-only for Ada → the scenario needed a
  driver-side turn; that's the `board_respond:` addition.
- Board writes through Caddy take ~45–75s → scenario timeouts are
  180–240s on write turns (kanban_review precedent).

## Verification done

- `python3 scripts/scenario-schema-check.py --scenarios-dir
  tests/scenarios-live` → 212 files, 0 violations (new scenario
  included).
- `ast.parse` on scenario-live.py; `turn_metrics` init pattern
  matches the http_check branch.
- Both new chaba YAMLs pass `yaml.safe_load` and the repo's SSOT
  pre-commit validation.

## Not yet verified (needs merge + deploy)

The scenario has NOT been run live — it only exists on the dispatch
branches. Activation path: merge the ada-voice branch → deploy via
`deploy-ada.sh` on idc03 → merge the chaba branch so
`ada-opencode-approval-probe` lands on the board → the hourly smoke
suite picks it up on ada-dev (:8005). First live run will exercise a
REAL bounded opencode job on idc02 (idc02 = card's "real
ada-opencode surface on idc02 (v2.2.5)").

Watch items (documented in the scenario header): model may skip the
board ask for a voice confirm — acceptable deviation, reads as
behavior drift on the turn-1 kanban assert; receipt-window expiry on
slow turns is mitigated by the re-preflight teaching + mismatch→fresh
triple recovery.

lessons:
- board-api /respond is owner-only — live ask->respond scenarios need a driver-side turn (added board_respond: to scenario-live.py); the model cannot play Tony's click.
- executor=opencode cards are NOT claimable on idc02 without a full action.lane_envelope passing prepare_profile_dispatch — bare dispatch cards silently never run.
- ada_opencode preflight limits can be staged as action.max_* fields on the card YAML so the model never has to supply them.
- approval_receipt binds card.updated — EVERY board write (ask, respond, comment) re-keys it; tool_guide now teaches re-preflight before dispatch.
- chaba SSOT pre-commit rejects jobs docs without `title` and plain-scalar `: ` sequences — quote or rephrase colons in prose.
