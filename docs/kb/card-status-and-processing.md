# Card Status and Processing — Low-Token Procedure

Status: defined 2026-11-09

## Purpose

Answer card and queue questions with the fewest reads that still prove the
state. This complements `docs/kb/board-api-read-door.md`; it does not create a
second queue or status source.

## One-pass procedure

1. **Scope first.** Extract the named card IDs, refs, executor, and the exact
   question. Do not scan the entire board when the user names one or a few
   cards.
2. **Read narrowly.** For a fleet overview, call `GET /queue` once. For named
   cards, call `GET /card/<id>` and request only needed fields; include
   `comms` only when a pending question, failure, or contradictory state needs
   investigation. Batch independent reads in parallel.
3. **Reconcile the executor once.** A board `running` or `failed` value is not
   proof of the external executor's current state. For Jules, use one session
   list for the batch; fetch session details/activities only for sessions
   whose state is awaiting input, completed, or inconsistent with the card.
   Read a PR and its checks only when the session/card points to one.
4. **Reuse decisions.** Read card `requests` and recent `comms` before asking
   again. If Tony already approved the plan, pass that answer to the waiting
   session once. Ask only for a genuinely unresolved decision.
5. **Do not poll-loop.** Take one timestamped snapshot, then continue an
   independent, non-duplicative task while remote work runs. Refresh only
   after a meaningful event, when the user asks, or when stale/contradictory
   evidence changes the answer.
6. **Close with evidence.** Distinguish queued, executing, awaiting input,
   PR-open, merged, and verified. A completed agent session is not a merged
   card. Record the artifact/PR and checks on the card; move to done only
   after the relevant merge and verification gates pass.

## Cost and timing

- Prefer deterministic reads and existing zero-Devin lanes. "No Devin call"
  does not guarantee zero provider quota, subscription, or machine cost.
- Give an ETA only when there is a measured service window. Separate execution
  time from queue wait and human-feedback wait; otherwise state the blocker and
  avoid promising a finish time.
- Do not start a live model benchmark or other billable action just to verify
  wiring unless its spend is authorized.

## Ada adapter

Ada already has a compact DevNest snapshot through `nest_status` and the
`kanban-brief` board index. For a queue overview, use `nest_status` once and
report its snapshot age/staleness. For card progress, use the index and read
only the named cards. If the card and executor disagree, inspect only that
session or PR. Preserve the same evidence, no-repeat, and no-poll-loop rules
without copying this whole procedure into her always-loaded prompt.

## Prior art

- `docs/kb/board-api-read-door.md` — narrow board projections.
- `docs/kb/devnest-performance-and-research-procedure.md` — stable context,
  compact manifests, and measured lane costs.
- `docs/ssot/kanban/cards/live-session-token-diet.yml` — historical Ada prompt
  and tool-schema token reductions; this procedure targets repeated
  orchestration reads instead.
