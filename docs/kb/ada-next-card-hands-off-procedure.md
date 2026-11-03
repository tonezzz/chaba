---
category: operations
type: runbook
status: defined
---

# Ada Next-Card Hands-Off Procedure

## Purpose

`/ada next` selects the next valuable backlog candidate for Tony to review.
It is a recommendation tool, not an automatic queue or dispatch mechanism.

## Command loop

```text
/ada next
  -> projected backlog read
  -> deterministic candidate scoring
  -> top candidates + reasons + blockers
  -> Tony chooses a card

/ada plan <ref>
  -> read the selected card
  -> produce scope, acceptance criteria, risks, and verifier

/ada handoff <ref>
  -> preview the canonical job envelope
  -> show executor, paths, artifacts, verifier, timeout, approvals

Tony explicitly starts processing
  -> typed dispatch contract
  -> isolated worktree
  -> OpenCode or another declared executor
  -> independent verifier
  -> review-ready artifact
  -> Tony approval for merge/deploy
```

## Selection policy

The tool ranks cards using only board-visible fields:

```text
positive:
  high/medium priority
  self-contained brief
  explicit test, verifier, schema, or documentation language
  read-only/OpenCode/Ada-compatible scope

negative:
  open requests or unresolved decisions
  manual-only action
  credentials, secrets, destructive, database, production, or deploy scope
  thin or missing brief
  title suggests fixed/completed/closed work
  card already claimed, running, or done
```

The result includes a score, reasons, blockers, and the next command. The
scoring is an aid to review, not a claim that the highest score is correct.
Ada must re-read the card before planning and must not invent missing scope.

## Hands-off boundaries

Ada may perform without another approval:

- projected board reads;
- candidate ranking;
- card status lookup;
- read-only plan generation;
- handoff preview;
- fixed local self-test.

Ada must stop for explicit approval before:

- dispatching a job;
- editing a worktree;
- writing a card or report;
- using credentials;
- changing a service or dashboard;
- merging, deploying, deleting, or self-modifying.

`finish` means the executor has produced the declared artifact, the
independent verifier passes, and the result is review-ready. It does not mean
automatic merge or deployment.

## Failure and escalation

- No safe candidate: report `no_candidate` and do not queue anything.
- Candidate has an open request: show the request and ask Tony to resolve it.
- Executor unavailable: keep the card queued; never silently fall back.
- Missing artifact, failed test, scope violation, or unknown exit: mark the
  attempt unverified and escalate.
- Stale board projection: refresh and re-read before making a recommendation.

## Evidence contract

Every processing attempt must retain:

```text
card/ref
selection score and reasons
executor/model/host/profile
worktree and allowed paths
input/output artifacts
tests and independent verifier
approval receipts
final status
```
