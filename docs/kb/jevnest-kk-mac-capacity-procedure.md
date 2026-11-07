# JevNest on KK-Mac — capacity-aware continuous work procedure

**Status:** standard procedure, card `jevnest-kk-mac-capacity-loop`  
**Parent:** DevNest  
**Decision family:** JevTeam  
**Executor:** KK-Mac local `qwen3:8b`

## Mental model

```text
DevNest
└── JevTeam                 decision/routing family
    ├── JEV                original decision engine
    ├── Jev Alternatives   jev-student, jevos, Laya, deterministic matchers
    └── JevNest             specialized bounded work sub-nests
        └── KK-Mac LLM     summary/extract/audit/safe-route queue
```

JevTeam chooses or approves the work family. JevNest owns the queue and
execution loop. A JevNest is not allowed to become an unbounded agent swarm.

## Admission

Before queueing or claiming work, require:

```text
heartbeat age <= 900s
ollama_ok = true
load_1m <= 4.0
disk_free_gb >= 20
owner/busy gate clear
```

The executable gate is `scripts/devnest/kk_mac_admission.py`.

## Owner-approved capacity window

When Tony explicitly grants an idle window, record the end time and use the
lane only until that deadline:

```text
owner permission window
-> refresh heartbeat
-> verify load/disk/Ollama
-> enable report feed, broker, producer, and worker
-> keep queue depth <= 10
-> keep normal concurrency at 1
-> stop intake and worker automatically at the deadline
```

For a short window, optimize throughput with more ready packages and shorter
polling, not uncontrolled parallelism. Allow concurrency 2 only for short
read-only requests when `load_1m < 2.5`, memory headroom is clear, and a
two-request verifier test has passed. Revert to serial mode immediately when
load rises, the owner returns, or disk approaches the floor.

The deadline is a hard stop: no new claims after it, and any in-flight
package finishes or records fallback. The physical Mac is not powered off by
this procedure; worker use and host power are separate controls.

## What to send

Only bounded, read-only packages:

```text
summary
operator_brief
structured_extract
safe_route
```

Every package carries:

```text
task_id
task_class
prompt/evidence
model
expect.required_keys
expect.enums
expect.facts
artifact
timeout
```

No package may request shell execution, repository mutation, credentials,
service control, destructive work, or publication.

## Refill policy

The producer runs when the admission gate is green and the queue depth is
below three:

1. Prefer real work from DevNest reports, host assessments, audit deltas,
   queue status, and outstanding operator briefs.
2. Then use approved benchmark/replay packages.
3. Never refill production capacity with synthetic soak tasks; soak is a
   benchmark and must be labelled as such.
4. Refill at most three packages per cycle and keep worker concurrency at
   one until a two-request load test is approved.
5. Stop producing when heartbeat/load/disk admission fails.

This keeps KK-Mac active without competing with the owner or exhausting
storage. A missing or stale heartbeat causes safe fallback, not queue
starvation.

## Completion and feedback

The worker must write:

```text
claim
artifact
usage
verdict
done/fallback
```

Independent verification checks the declared schema and facts. Each result
feeds back into JevTeam metrics:

```text
queue wait
wall time
eval tokens
verifier pass
fallback reason
human intervention
cost
```

Weekly review decides whether to increase capacity, keep concurrency at one,
change the model, or retire the lane. Promotion to automatic JEV routing
requires a verified soak and no owner-impact incidents.

## Current next step

The KK-Mac worker and 10-package semantic soak are complete. The missing
piece is the capacity-aware producer that refills the dedicated queue with
real report/audit work when KK-Mac is green.
