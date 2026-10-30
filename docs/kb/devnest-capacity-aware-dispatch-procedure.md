# DevNest capacity-aware dispatch procedure

**Scope:** KK-Mac JevNest and Colab GPU Nest workers  
**Parent:** DevNest  
**Decision family:** JevTeam  
**Goal:** keep eligible workers useful without inventing work, wasting quota, or
interfering with shared hardware.

## Why workers look idle

Idle time is currently expected when one of these is true:

```text
no real task spec is in the worker inbox
worker admission is stale or unsafe
Colab has no fresh managed GPU runtime
Colab queue was not staged before the runtime launch
the available work is not suitable for that lane
```

The fix is not to run synthetic filler. The fix is to prepare a ready
backlog of real, bounded work before capacity appears.

## Standard flow

```text
DevNest cards/reports/audits
    -> normalized task spec
    -> JevTeam lane decision
    -> lane inbox
    -> capacity gate
    -> claim/run
    -> independent verifier
    -> durable artifact + usage
    -> feedback to JevTeam
```

Every task spec declares:

```text
task_id
task_class
repo/repo_root when relevant
evidence or prompt
lane/executor
model
expect/verifier
artifact root
timeout
fallback
```

## Refill loop

The capacity producer runs every five minutes:

1. Read current worker heartbeats and queue depth.
2. Select real ready work in this order:
   - outstanding operator reports and audits;
   - host/service status deltas;
   - structured extraction from new evidence;
   - held-out evaluations and replay fixtures;
   - cache/prep work for an already-approved finite batch.
3. Apply the lane admission gate.
4. Fill only to the lane watermark.
5. Leave unsuitable work for JevTeam to route elsewhere.

No producer creates synthetic production tasks merely to increase utilization.
Benchmark and soak packages are labelled separately and have their own quota.

## KK-Mac JevNest

Queue: `gdrive:ada-nest-kk-llm`

Admission:

```text
fresh heartbeat
Ollama healthy
load_1m <= 4.0
disk >= 20 GB
owner/busy gate clear
```

Watermark and concurrency:

```text
target queue depth: 3
refill: at most 3 packages/cycle
normal concurrency: 1
concurrency 2: only after a realistic two-request test
```

Allowed classes are `summary`, `operator_brief`, `structured_extract`, and
`safe_route`. Repository mutation, credentials, destructive actions, coding,
video, and long agent loops go to another lane.

If any gate fails, do not wait for KK-Mac. Mark the attempt fallback and route
to the next eligible lane.

## Colab GPU Nest

Colab is an ephemeral finite-batch worker, not an always-on endpoint.

Before launch:

```text
fresh managed T4/A100 runtime registered
no competing managed runtime
GPU present
all JOBS.py entries and pack manifests staged
dependencies/cache artifacts verified
durable artifact roots declared
```

The queue runner snapshots `JOBS.py` and `packs/` at launch. Mid-session
uploads are not discovered until the next launch. Therefore stage a complete
batch before starting the runtime.

Use the available GPU efficiently by ordering:

```text
cache-independent held-out assessment
-> cache/model prep for the next package
-> finite GPU batch
-> verifier/QC
-> durable publish
```

Do not start a second runner or spend quota merely because the runtime is
idle. If no approved finite batch is ready, stop at the next safe boundary.

## Efficiency scoreboard

Review per lane weekly:

```text
eligible minutes
productive minutes
queue wait
verified successes
fallbacks and failures
wall time
tokens/GPU time
cost
owner-impact incidents
```

The target is not maximum utilization. It is verified output per available
minute, with zero unsafe work and no quota or owner-impact surprises.

## Current gap and next implementation

KK-Mac now has a capacity producer. Colab has the queue and assessment-first
procedure, but DevNest does not yet have one shared capacity broker that
converts ready cards/reports into normalized lane inbox specs. Implement that
broker next, starting with read-only reports and finite Colab evaluations.

## Bounded package planner (proposed)

A planner can improve fanout, but it must be a proposal generator, not a
queue writer:

```text
real evidence
-> planner package on KK-Mac
-> candidate-spec artifact
-> deterministic validator on tony-dell
-> normal JevTeam broker
-> bounded worker packages
```

Guardrails:

```text
maximum 3 candidates per source/cycle
depth 1 — planner output cannot create planner tasks
source evidence required
dedupe by source hash and task ID
allowed classes and artifact roots only
no secrets, credentials, mutations, or publication
no automatic replanning after verifier failure
```

The planner must not write to `gdrive:ada-nest-devnest/inbox/` directly.
Without the deterministic upstream validator, it would create synthetic work,
feedback loops, and queue amplification rather than useful capacity
utilization. This proposal is tracked as `OPS-1027`.
