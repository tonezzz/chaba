# DevNest free-lane pilot A — deterministic docs artifact

- **Card:** `devnest-free-pilot-doc` (OPS-0895)
- **Parent pilot:** `devnest-free-lane-savings-pilot` (OPS-0885)
- **Date:** 2026-10-26
- **Runner:** tony-dell (dispatch worktree)

## Purpose

Produce a small, fully verifiable docs-only artifact through the free
OpenCode lane, then let the standard runner closeout verify and
auto-merge it. This is pilot job A of the free-lane savings pilot: prove
that a trivial deterministic chore can run end-to-end on a free model
(worktree → change → gate → commit/push → merge) with token/time/intervention
evidence, before heavier pilot classes are attempted.

## Target lane

`free_lane` — the free OpenCode executor lane (`free-opencode` in
`docs/ssot/infrastructure/ssot.devnest-lanes.yml`). Runs in a
`dispatch/<tid>` worktree with the normal closeout/merge gate; suited to
single-step verifiable chores like "write the doc". Escalation on gate
failure: paid_frontier or devin.

## Model

`flash-lite` — LiteLLM alias `litellm/gemini-3.5-flash-lite` (Gemini
Flash Lite free tier). Expected cost ~$0; expected tokens ~2–12k per
chore.

## Pilot metrics checklist

The three headline metrics every pilot job must capture (per the
OPS-0885 spec — cost, quality, oversight):

- [ ] **Cost per passed gate** — LiteLLM spend delta + input/output
  tokens vs the Devin baseline for a matched task.
- [ ] **Gate + merge success** — declared artifact exists, verifier/done
  gate passes, and the dispatch branch auto-merges without manual repair.
- [ ] **Human intervention minutes** — supervision time required beyond
  queueing the card (fixes, re-prompts, manual merges); target zero for
  this class.

## Done gate

- [x] This file exists at `docs/reports/devnest-free-lane-pilot-a.md`
      with all required headings.
- [ ] Branch auto-merges via runner closeout (no manual push).
