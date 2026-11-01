---
category: operations
type: runbook
---

# Missed-job sweep — board state versus evidence

Use this when Tony repeats a request, asks what remains, reports a blank or
broken production surface, or when a `doing`/`running` item has gone quiet.
It complements the Frustration Procedure and `devin-session-audit`; it does
not replace either one.

## Procedure

1. **Capture the scope.** Read the active focus and the relevant board cards.
   Keep already-answered decisions as instructions; do not ask for them again.
2. **Inventory board state from board-api.** List cards in `doing`/`review`,
   `action.status` in `queued`/`running`, and requests with an answer but no
   recorded outcome. Record card ID, last update, runner/host, and the next
   expected artifact.
3. **Verify the claimed execution.** Match every `running` action to a live
   task unit/process and runner host. Check task/session IDs, worktree/branch,
   exit result, and whether the artifact landed in the declared durable home.
   A long-lived IDE or runner service is not evidence that a card's job is
   running; an exit code of zero is not proof that the deliverable exists.
4. **Verify the user-facing surface.** For an iframe or Web UI, check the
   exact source URL and the actual consumer page with PlayLive. Record the
   screenshot/DOM metrics and verify the expected text/cards/widgets. HTTP
   200, a configured iframe, or an active service alone does not pass.
5. **Verify answered requests were acted on.** Find the resulting deploy,
   queued task, file, route, or other outcome. If no actor acted, either
   execute the already-approved reversible step or record the real gate;
   never treat `answered` as `done`.
6. **Cross-check session artifacts.** Run `devin-session-audit` over summaries
   newer than its marker, excluding the current session. Confirm files are
   committed, reports/pages exist, cards have durable comms, and no claimed
   output lives only in chat, `/tmp`, a worktree, or an expired runtime.
7. **Classify every finding.** Use one of: verified complete, active with
   live evidence, stale status, missing artifact, duplicate, or blocked on a
   concrete decision. Update the existing card where possible; create one
   board-api card per genuinely new miss. Do not create duplicates.
8. **Fix safe work and correct the board.** Repair reversible, authorized
   items. Put stale `running` actions on hold when no process exists; leave
   policy, public exposure, secret, or spend gates blocked until approved.
   Add a dated comm with the evidence and next owner.
9. **Report a checkable scoreboard.** For each item list card ID, evidence,
   state, next action, owner, and blocker. State unverified items explicitly.
   Invoke the Frustration Procedure before making any completion claim.

## Thresholds

- A `doing`/`running` item with no new progress comm or live process for 24
  hours is stale and must be checked, not repeated or left presented as active.
- An answered request without an outcome comm is an unacted request.
- A completed UI claim requires a PlayLive screenshot of the exact target
  surface and a config/API read-back.
- For model-cost claims, run all Frustration Procedure M1–M8 checks. For
  non-model work, mark those model-specific checks `N/A` with the reason and
  use the applicable production-surface checks instead.

## Current implementation limits

This is a manual procedure; no automatic missed-job timer is deployed. The
board, session audit marker, job SSOT, and PlayLive checks are the sources of
truth. A daily automated stale-card sweep can be added separately after its
false-positive and ownership behavior is specified.
