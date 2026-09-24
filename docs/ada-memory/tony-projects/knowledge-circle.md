---
kind: procedure
status: active
subject: knowledge-circle
attribute: plan
---

# Ada Knowledge Circle — closing the loop

Status: APPROVED 2026-09-21 · implementation in progress

## The circle

    CAPTURE → DISTILL → REVIEW → ACTIVATE → APPLY → VERIFY → REINFORCE
        ↑                                                        │
        └──────────────  CORRECT (supersede/retract)  ◄──────────┘

Capture→Activate is built and deployed. Apply is built (tiered recall).
Verify and Reinforce were the open side — nothing recorded whether
recalled knowledge produced a correct outcome, and nothing aged,
reinforced, or retired knowledge based on use.

Goal: every memory doc earns its keep or dies. Every miss becomes a
candidate lesson. Every application of knowledge feeds back into the
doc that supplied it.

## Loop-closing mechanisms (ordered by cost/benefit)

### 1. Usage accounting on hits

When `ada_memory_search` returns a doc that Ada uses in its answer,
bump meta: `use_count += 1`, `last_used: <date>`.
Buys: "which memories are load-bearing", a ranking signal, and the
substrate for everything below. `last_verified` is NOT bumped on use —
use ≠ truth.

### 2. Outcome feedback verb

When applied knowledge produces a known result, record it on the doc:

- Voice: "that shop turned out fine" → `outcome: good`, bump
  `last_verified`, `confidence +`.
- Purchase bank: `kind: check` docs gain `outcome: bought_good |
  bought_bad | skipped`. Criteria that produce bad verdicts lose
  confidence; confirmed criteria gain it.
- Procedures: "that fix worked" → `last_verified` bump.

This converts the bank from a notebook into a learning system.

### 3. Miss→lesson pipeline

Recall misses are already logged (recall-drift-report). Weekly job
clusters miss queries by topic; a topic with ≥3 misses and no active
doc → auto-draft a `kind: note, status: draft` gap note into `inbox/`
("Ada couldn't answer questions about X") — human fills or dismisses.

Closes: "questions Ada can't answer" → capture.

### 4. Staleness sweep → iPhone confirmation

Weekly job scans banks for `last_verified` > 90d on `use_count > 0`
docs. Emit one digest via chaba-events + `notify.mobile_app_tony_ip`
using the existing APPROVE_/DENY_ action pattern:

    "You told me the gate remote lives in the hallway cabinet —
     still true?"  [STILL TRUE]  [CHANGED]

APPROVE → `last_verified = today`. DENY → prompt for correction →
supersede. Reuses existing machinery; turns passive expiry into active
re-verification.

### 5. Correction-aware distillation

Session-close extraction also detects:
(a) user corrections ("no, it's actually...") → supersede candidates,
(b) procedures that worked → `kind: procedure` drafts,
(c) repeated unanswered questions → gap notes.

Drafts still flow through inbox review — the human gate stays; it gets
better raw material.

### 6. Confidence enforcement

`confidence` was advisory (prompt-level). Docs below threshold are
returned tagged `unverified`; the model must hedge or escalate rather
than speak them as fact. Outcome feedback (#2) is what moves
confidence — the gate is what makes it matter.

### 7. Graduation path

Ladder of authority so lessons can harden upward:

    voice note → bank doc (draft) → curated bank doc (active)
      → vault doc → SSOT/runbook → code default / system instruction

Each step raises authority and change-cost. Vault↔MDDB is wired;
vault→SSOT stays deliberately manual (human-paced).

### 8. Canary recall set (measurement)

A fixed set of ~10 known-answer questions per instance, run weekly,
scoring whether Ada's banks produce the right answer — a correctness
metric complementing the drift report's retrieval metric. Same pattern
as the Open Notebook 8-question benchmark.

## Operational shape

- meta_schema additions: `use_count`, `last_used`, `outcome`
  (consumed by render + sync + warn-on-drift as usual).
- Two weekly timers (miss aggregation, staleness sweep) — emit into
  existing chaba-events / inbox surfaces.
- One prompt change (extraction), one gate change (confidence tag),
  one small write path (use_count on hit).
- Everything fails soft: if feedback breaks, recall works as today.

## Deliberately open

- NotebookLM tier stays append-only and unverified — archive, not
  answer.
- Draft→active stays human-gated; automation proposes, humans promote.
- No automatic `confidence`-decay deletion — retracted docs keep
  their audit trail.

## Implementation order

1. use_count/last_used instrumentation (measure first)
2. Correction-aware distillation + miss→gap drafts
3. Staleness sweep + iPhone confirm
4. Outcome verb + confidence gate
5. Canary set once there's traffic to measure
