# dispatch-outcome — opencode-explicit-executor-routing

Implemented the explicit executor contract for delegated kanban cards.
`action.executor ∈ {opencode, devin, script, manual}` plus optional
`action.agent_profile`, `action.model`, `action.target_host`, and
`action.artifact` are now first-class, validated, and enforced end to
end — an unservable declared executor never silently falls back.

## What changed

- **scripts/board/dispatch_repos.py** — `EXECUTORS`, `MODEL_ID_RE`,
  `PROFILE_ID_RE`, `HOST_ID_RE`; helpers `card_executor`,
  `card_profile` (agent_profile wins, action.profile is the pre-contract
  alias), `card_target_host`, `model_provider`, `executor_blurb`.
  `session()` now surfaces executor/provider/model/profile/card from
  task meta; `close_out()` carries them into its result;
  `close_out_notes()` emits the "ran under executor=… provider=…
  model=… profile=…" comms line.
- **scripts/board/board-api.py** — `ACTION_KEYS` gained executor,
  agent_profile, profile, target_host, artifact. `do_create` validates
  executor membership, profile-id/host-id shapes, safe repo-relative
  artifact paths, and a widened model regex (provider-qualified ids
  like `litellm/or-claude-fable-5.1`). `do_claim` persists
  executor/agent_profile/target_host atomically and **refuses** a claim
  that disagrees with a declared executor. `queue_starve_warn` flags
  executor=manual alongside the type guard.
- **scripts/board/runner-agent.py** — `opencode_bin()` resolves
  $OPENCODE_BIN → PATH → ~/.opencode/bin → ~/.local/bin (systemd PATH
  never carries the .bashrc addition). `claimable()` honors the
  contract: manual/unknown fail closed, target_host pins, opencode
  requires OPENCODE_LANES=1 + binary + push creds; the new
  `executor_defer_reason()` posts a debounced comms note instead of
  silent starvation. `start_task()` routes explicit executors before
  any classification — explicit opencode failures return an error,
  never a devin run; executor=devin skips classification entirely.
  `start_opencode_lane()` now resolves profile via the contract fields,
  model precedence action.model > lane > profile default, and stamps
  meta.json (executor/provider/model/profile/card/lane/repo_root) +
  usage.json while teeing the event stream to events.jsonl. New
  `finish_opencode_lane()` runs before the merge gate: event audit →
  usage.json enrichment, declared-artifact landing into the worktree
  (message-mode extraction or file-mode pickup, confined to the
  profile's artifact.dirs), manifest.json + held-out verifier +
  verdict.json, a lane_gate ledger row — merge is held
  (verified=False) unless the declared artifact lands AND the verifier
  passes AND no denials/mutating commands. Claim comms detail
  executor/profile/model.
- **scripts/board/kanban-dispatch.py** — the claim loop skips declared
  non-devin executors and target_host mismatches with a printed reason
  (never silently claims them as devin work); `start_pending` skips
  lane classification for declared executors and passes
  DISPATCH_CARD/EXECUTOR/PROVIDER/PROFILE/TARGET_HOST env; the
  dispatched comms line carries the executor blurb.
- **scripts/devin/devin-dispatch.sh** — `_meta_write` stamps
  executor/provider/model/profile/card/target_host into meta.json and
  writes usage.json — durable accounting even when the provider
  reports nothing.
- **docs/ssot/kanban/cards/opencode-executor-routing-smoke.yml** — the
  read-only smoke card: queued, executor=opencode, ops-readonly
  profile, flash-lite, target_host=idc02, declared artifact
  `evals/opencode-lane/out/executor-contract-smoke.json`, expected_goal
  file-exists. The agent holds no write tools — the runner lands the
  artifact — so no production/write capability expansion.
- **docs/ssot/jobs/board/2026-10-28-explicit-executor-contract.yml** —
  the durable decision/infra trail for the contract.

## Result

- All work committed to `dispatch/20261028-094504-add-an-explicit-executor-contr`
  (`c08108e50`). No push, no deploy, per the card rails.
- Tests: `tests/board/test_executor_contract.py` adds 40 cases
  (explicit opencode, unavailable opencode, explicit devin, absent
  executor classifier fallback, artifact/verifier merge holds,
  board-api validation, kanban-dispatch skips, regexes). Full suites:
  289 tests/board + 116 tests/devnest pass. `make ssot` validation:
  my two new YAMLs are valid (the 2 errors in the run are pre-existing
  files, not this change).

## How to verify

- `python3 -m unittest discover -s tests/board -t .` — all green.
- Watch `opencode-executor-routing-smoke` after merge: idc02's
  runner-agent should claim it (executor=opencode), produce
  `dispatch/<task>` worktree + meta/usage/events/manifest/verdict +
  landed artifact, and the closeout comms should show
  "ran under executor=opencode…" — a hold (verified=False) instead of
  a silent devin run is a PASS for the contract.
- Negative probe: queue a card with `executor: opencode` on a host
  without OPENCODE_LANES — it must stay queued with a defer comment,
  not get claimed.

lessons:
- runner-agent deploys as a single file — contract constants/helpers
  that kanban-dispatch imports from dispatch_repos must be duplicated
  locally in runner-agent (EXECUTORS, card_profile, model_provider).
- opencode is NOT on the systemd user-manager PATH (~/.opencode/bin
  only enters via .bashrc) — capability checks must resolve the binary
  explicitly, not rely on PATH.
- provider must be computed AFTER lane model resolution — an
  env-only lane fallback can change DISPATCH_MODEL after the executor
  env block runs.
