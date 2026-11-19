# Devin workflow & error-handling standard

**Status:** codified standard (DEV-0253) — written 2026-11-19 by a
dispatch session for card `standardize-devin-workflows-error-handli-e19df2`.
Tony's scope answer: *"chaba — audit current error-handling patterns
across lanes, write ssot.procedures entries + AGENTS.md rule"*.

This document is the audit + the distilled contract. **Nothing here is
new machinery** — every rule already runs in production somewhere in
the lane stack. The standard exists so the *next* lane copies the
proven pattern instead of improvising a weaker one, and so reviewers
can flag deviations.

## Lanes audited

| Lane | File | Failure surface |
|---|---|---|
| Served claim loop | `scripts/board/kanban-dispatch.py` | claim gates, auto-retry, park, ops-event, notify |
| Satellite claim loop | `scripts/board/runner-agent.py` | per-card retry ledger + backoff, defer notes, ratelimit cooldown, GPU/watchdog guards |
| Verified gate | `scripts/board/merge-sweep.py` | three-way verify (exit ∧ work ∧ goals), fail → requeue-or-failed |
| Worktree reaper | `scripts/board/dispatch-wt-sweep.py` | salvage-before-reap, keep-on-doubt |
| Mutation door | `scripts/board/board-api.py` + `publication.py` | flock serialization, outbox retry + dead-letter, answers.jsonl fan-out |
| Session launcher | `scripts/devin/devin-dispatch.sh` + `devin-dispatch-watch.sh` | prompt rails, needs-input routing, transcript verdict over exit code |
| Generic job envelope | `scripts/devin/job-run.sh` | exit-42 / `NEEDS-INPUT:` protocol, event+push+mddb ledger |
| Request lifecycle | `scripts/board/request-sweep.py`, `answer-sweep.py` | escalate unanswered, execute answered verbs, defer conflicts |
| Unattended gate | `scripts/board/waiting_cards.py` | eligibility + preflight + R0–R4 recoverability |
| Autonomy envelope | `docs/ssot/infrastructure/ssot.devin-autonomy.yml` | kill switch, quiet hours, budgets, tier ceiling, failure_rule |

## The standard — 10 rules

### 1. Fail loud, with bounded evidence

A lane never fails silently. Every failure lands on the card's comms
with a short reason (~240–280 chars — enough to act on, not a dump)
and is stamped into `action.last_failure` so the next attempt inherits
it. `verified: false` means *checked and failed* — deliberately
distinct from "verified withheld/unproven", which holds for a human
instead of auto-retrying.

*Exemplars:* `merge-sweep.fail_attempt` (verified=False + last_failure
+ comms + requeue-or-failed in one flock'd write), `kanban-dispatch`
merge-close-out notes, runner `retry_record_failure` comms.

### 2. Bounded retries; re-arm is a deliberate act

Two retry ledgers exist, each with different scope — a new lane must
reuse one, never invent a third:

- **`action.attempts` / `action.max_attempts`** (dispatch-side):
  counted *at claim time* (`mark_start`); a verify-gate failure
  requeues while `attempts < max_attempts` (default 2 total dispatches,
  `KANBAN_MAX_ATTEMPTS`), then `action.status: failed` / parked per
  `retries_per_card` in `ssot.devin-autonomy.yml` ("exhausted cards
  park, they don't loop").
- **`retry-ledger.json`** (runner-side, per-host): consecutive fails
  back off exponentially (`1800·2ⁿ⁻¹`s, cap 6h) and hold the card on
  *that host* at `RUNNER_RETRY_MAX` (3). A hold never pins the card —
  another runner may still serve it.

Re-arm happens only on a **deliberate human verb** — the comms texts
"retry requested" / "re-queued" / "queued for processing" forgive the
ledger. Producer re-queues ("re-spawned from report page", sentinel
re-opens) deliberately do **not** forgive — that path was the Nov 8–9
flood driver (~130 worktrees on tony-omen). `attempts` bumps are not a
forgive signal either (a sibling dispatcher's `mark_start` would
ping-pong the flood between hosts).

*Exemplars:* `runner-agent.retry_gate` + `RETRY_REARM_TEXTS`;
`publication.py` outbox (30s·2ⁿ capped 30m, dead-letter at
`MAX_ATTEMPTS`).

### 3. Carry the failure into the next attempt

A requeued card's evidence travels forward: `RETRY_RAILS` injects
`last_failure` into the next session prompt with the order **"fix the
reported failure FIRST; do not repeat the failed approach"**, and the
session is pointed at the card comms for the full trail. Empty-dispatch
failures stamp `action.sweep.zero_commit` — the QC scoreboard's
counter — so a broken lane shows up as a count, not a mystery.

### 4. Blocked ≠ failed

A lane or session that needs a human **asks**; it does not exit
nonzero, burn a retry, or fake success:

- Card dispatches: `POST /request` on board-api, keep working if
  possible; answers arrive in `$TASK_DIR/answers.jsonl` (newest line
  per `request_id` wins; `kind:"comment"` lines are review input).
- job-run jobs: write `$TASK_DIR/needs-input.txt` (line 1 = the
  question) **or** exit 42 after printing `NEEDS-INPUT: <question>` —
  the wrapper flips the job doc to `awaiting-user` and pushes the
  question to Tony.
- devin-dispatch sessions: same `needs-input.txt` contract — the watch
  timer routes it to the iPhone push + job ledger instead of reporting
  a failure.
- `awaiting_action` on a card is reserved for **deterministic gaps a
  human must fix** (e.g. fleet-unclaimable labels, retry cap) — never
  for per-host refusals.

### 5. Advisory components degrade, never block

Anything that reports, primes, or notifies is warn-only: a dead API,
failed primer, or lost ops-event must never stop a claim loop, merge,
or reap. Every advisory call is wrapped (`except → warn`/return) —
`lesson_primer` ("advisory — never block a run"), `_publish`/`_notify`
("a dead api never blocks the claim loop"), `ops_event`,
`note_salvage`, job-run's `mddb_job`/`notify_iphone`/`emit_event`
(rc always 0).

### 6. Gate at claim time, not mid-run

Capability checks run **before** work starts, so a lane defers cleanly
instead of dying halfway:

- push-credential guard: `push:<repo>` label fast-path, else a live
  `git push --dry-run` probe (TTL-cached) — a git@ remote is no proof
  (ADA-0673's chaba-only deploy key).
- GPU preflight: free VRAM must cover max(card need, host floor); a
  need exceeding total VRAM is *refused* (fix the spec — it can never
  fit), a shortfall defers.
- Claim gates: load/core, quiet hours, kill switch
  (`/tmp/no-kanban-dispatch`), daily session budget, host cap,
  autonomy tier ceiling, waiting-cards eligibility + R-class (R3/R4
  never claimed in any mode).
- Provider rate-limit cooldown: a dead unit carrying a 429/throttle
  signature arms a host-local hold on ALL new claims (~30m) — the lane
  model is a fleet-shared quota; re-claiming burns every queued card's
  attempts, not just the card that hit the wall.

Defers are **comms-noted and debounced** (`note_defer`: at most once
per window per distinct reason) — the board always shows *why* a card
waits, without spam.

### 7. Shared-state writes under the flock; probes outside

Card mutations hold `/tmp/board-api.lock` and are kept cheap — no
network, git, or `systemctl`/`journalctl` inside it (the 2026-11-17
convoy: stacked probes under the flock 503'd board-api writes).
kanban-dispatch's phase-A0 surveys all probes lock-free, then takes
the flock for mutations only. Remote-backed board-api endpoints
serialize separately under `/tmp/board-api-wp.lock`; deploys under
`/tmp/pfg-deploy.lock`.

### 8. Nothing unproven is destroyed

Reapers keep what they can't prove safe: `dispatch-wt-sweep` reaps a
worktree only when it's past the forensic window, no unit is active,
evidence is captured, **and** its head is reachable from origin — an
unpushed head is salvage-pushed to `refs/heads/wip/dispatch/<task-id>`
first (comms-logged), and when origin can't be reached or HEAD is
unreadable the tree is **KEPT**. Unverifiable state always resolves
toward "hold for a human", never toward deletion. (Merge-sweep mirrors
this: ambiguous exit/work evidence → `hold`, not `fail`.)

### 9. Exit codes mean "crashed", not "found something"

Completed runs exit 0 — findings report via comms / focus-inbox /
ops-event / reports. Nonzero is reserved for the lane itself breaking,
so a red unit means "the machinery failed", never "the audit found
issues" (the `timer-expectations` procedure, OPS-0581). The dispatch
watch goes further: the transcript verdict beats the exit code — a
permission-rejected session exits 0 but reports `failed:permission`,
and a missing transcript + missing exit code is "never started", not
"success".

### 10. Finished ≠ verified

A session exiting 0 is not proof of delivered work. The verified gate
is a three-way conjunction — unit exit evidence ∧ produced-work
(branch head vs base tip / merged ancestor) ∧ `auto_done_when` — and
each leg can return pass / fail / *unverifiable*. `verified` is
stamped only on the all-pass path; the merged-but-failed case
withholds the stamp for a human rather than auto-closing
(dispatch-empty-closeout-verification-gap).

## Gaps and tensions found in the audit

Recorded for future cards — none block this standard:

- **Three retry counters, different semantics** —
  `action.attempts`/`max_attempts` (card-global, dispatch-side),
  runner `retry-ledger.json` (per-host, consecutive), and
  `retries_per_card` in the autonomy policy (also attempts-based, →
  `held`). They interoperate correctly today but the semantics differ
  ("total dispatches" vs "consecutive fails" vs "policy park"). A
  future card could unify the vocabulary; the ledgers themselves must
  stay separate (card-global vs host-local scope is real).
- **Vendored twins drift-watch** — runner-agent carries single-file
  copies of `waiting_cards.evaluate`, `RATE_LIMIT_PAT`, and
  `dr.repos()` resolution (it deploys standalone). Parity tests cover
  the signature table; the eligibility mirror is convention-kept. The
  recurring "installed runner-agent drifted from repo" defers on the
  card show the deploy path itself is the weak link — redeploy via
  `scp scripts/board/runner-agent.py <host>:~/.local/bin/runner-agent`.
- **Silent-success inference in dispatch-watch** — when a task dir has
  neither transcript nor exit_code the watch skips it, but a finished
  unit with no record at all used to infer "success"; today it still
  labels `(collected,inferred)` success when journal evidence is
  absent (best-available-signal). Acceptable, worth knowing.
- **`awaiting_action` semantics are convention** — producers other
  than `note_defer` can stamp it; nothing enforces the
  "deterministic-gap-only" rule beyond review.

## Pointers

- AGENTS.md: "Devin workflow & error-handling standard" duty
- `docs/ssot/ssot.procedures.yml`: `devin-error-standard`,
  `session-blocked-protocol`
- `docs/ssot/infrastructure/ssot.devin-autonomy.yml`: tiers, levers,
  waiting-cards contract
- `docs/ssot/jobs/board/2026-11-19-devin-workflow-error-standard.yml`:
  this job's record
