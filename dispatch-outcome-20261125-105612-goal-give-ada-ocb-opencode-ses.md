# Dispatch outcome — opencode-session-start-recall-injection (attempt 2)

## What happened

Attempt 1 (09:05 dispatch) actually completed the work — commit `133623cd1e`
added `.opencode/instructions/session-start.md`, registered it in
`opencode.jsonc`, and wrote the jobs trail
`docs/ssot/jobs/session-summary/2026-11-25-opencode-session-start-recall.yml`.
It failed at the merge gate, not on content: "pytest unavailable — no test
evidence" + a dirty worktree (2 uncommitted files) + a 39-commit-behind
checkpoint warning. Tony's verify-queue triage held the card back.

This attempt cherry-picked `133623cd1e` onto current master as `648e49ee1a`
(clean pick, no conflicts) and re-verified everything.

## State of the acceptance criteria

- **One command**: `/recall` — `.opencode/commands/recall.md`, already merged
  via PR #207 (squash `800d086aae`). Runs `chaba-session-capture render
  --if-stale` (repo fallback `scripts/chaba/render-memory.py --if-stale`),
  reads `~/.local/share/chaba/context.md`, injects a bounded ~4k-char
  pointer-first head. Read-only, no secrets.
- **Automatic**: `.opencode/instructions/session-start.md` (NEW this card) is
  an always-on instruction registered in `opencode.jsonc` — on resume-type
  sessions the agent is told to run `/recall` first and treat output as a
  resume signal, not truth.
- **Option B (plugin auto-inject)**: assessed feasible
  (`ctx.session.hook("context")` / `chat.system.transform` can edit
  `event.system`) but deferred — version-coupled plugin API, per-host
  install; not needed since acceptance allows "one command OR
  automatically". Rationale recorded in the jobs yml.
- **DEV-0038 pointer note**: already posted on parent card
  `publish-promote-knowledge-capture-ssot-w-d34a39` at 09:11 (verified in
  card comms).
- Follow-up card OPS-1347 (`opencode-recall-command-followup`) is `done`.

## Verification performed

- `git cherry-pick 133623cd1e` → `648e49ee1a`, clean.
- `opencode.jsonc` parses as JSON; `instructions` lists both
  `session-capture.md` and `session-start.md`.
- `python3 scripts/chaba/render-memory.py --check` → exit 0, clean (no
  writes).
- `.opencode/commands/recall.md`, `.opencode/instructions/session-start.md`,
  and the jobs yml contents reviewed — bounded, pointer-first, stale/missing
  handled explicitly.

## Files changed (this dispatch)

- `.opencode/instructions/session-start.md` (new, via cherry-pick)
- `docs/ssot/jobs/session-summary/2026-11-25-opencode-session-start-recall.yml` (new, via cherry-pick)
- `opencode.jsonc` (instructions array +1 entry, via cherry-pick)
- `dispatch-outcome-20261125-105612-goal-give-ada-ocb-opencode-ses.md` (this file)

## How to verify after merge

1. `cat .opencode/instructions/session-start.md` and confirm
   `opencode.jsonc` `instructions` includes it.
2. In an OpenCode session on a host with the session-capture playbook
   applied, run `/recall` — expect bounded context.md head + `as_of`
   timestamp; on hosts without it, the command must say context is
   missing and fall back to SSOT-first retrieval.

## Known residual

- The dispatch merge gate may again hold on "pytest unavailable — no test
  evidence"; this change is markdown/JSONC config with no Python surface,
  so there is nothing meaningful to unit-test. If the gate requires test
  evidence regardless, that is a gate-policy question for Tony, not a code
  gap.
- `context.md` is rendered per-host; ada-ocb lane hosts need the
  session-capture ansible playbook (or one manual `render-memory.py` run)
  before `/recall` has content — the command degrades gracefully.

lessons:
- A dispatch "failure" can be a merge-gate hold, not bad work — always check card comms and `git cat-file` for the prior commit before redoing it; cherry-pick beats rewrite.
- Dispatch merge gate "pytest unavailable — no test evidence" fires even for docs/config-only diffs; expect the hold and say so plainly in the outcome.
- `git fetch` of a specific dispatch branch failed with empty-object errors against the shared object store; the commit was still reachable locally via `git cat-file`/`git show` — check local objects before assuming work is lost.
