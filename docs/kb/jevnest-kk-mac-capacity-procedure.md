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

## The lane worker (kk_mac_lane_worker.py)

`scripts/devnest/kk_mac_lane_worker.py` is the dedicated consumer for
`gdrive:ada-nest/kk-llm`. It replaces generic `nest-worker.py` on this
remote — generic workers still own `gdrive:ada-nest/packs` (GPU/video/
coding packs) and never see the kk-llm queue.

Per pass (launchd `StartInterval=60`, always `--once`-equivalent):

1. **Gate** — deny exits clean, queue untouched:
   - `DEVNEST_KK_MAC_ENABLED != true` or the drain file
     (`~/.cache/kk-llm-worker.drain` by default) — instant hold.
   - `--host local` (production on KK-Mac): `local_snapshot()` — local
     ground truth for ollama /api/version, vm.loadavg, statvfs, smctemp,
     `tmux ls` owner/busy — same thresholds as the heartbeat gate.
   - `--host kk-mac` (supervised fleet runs): the MDDB heartbeat
     `snapshot()` — same fields, ≤15 min stale.
2. **Claim** — first-writer-wins `claim/<worker>` file, settle,
   verify-first — identical semantics to `nest-worker.py` (imported,
   not forked). Stale claims >60 min released; `fallback` markers hold a
   pack for `--fallback-retry-min` (30 min default) then auto-retry.
   `--max-packs` bounds claims per pass (1 normal, hard cap 2).
3. **Pre-claim admission** — `inputs/task.json` must exist and carry an
   admitted `task_class`, non-empty prompt ≤6000 chars. Anything else —
   including video/GPU/coding/destructive packs that land in the queue —
   is never claimed.
4. **Execute** — `kk_mac_executor.run_contract`, never pack `run:`/`run_sh`
   code: heartbeat admission + live memory guard + bounded
   `/api/generate` (`think:false`, `temperature:0`) + independent
   schema/fact verifier.
5. **Close** — `done` (verdict pass + artifacts verified remote-side),
   `fallback` (lane-condition or invalid output — held, retryable), or
   `failed` (terminal contract violation — needs a human). Claim always
   released. Result record (`out/result.json` + `kk_mac_result.json` +
   `verdict.json`) persists admission, memory samples, usage, checks.

### launchd install / rollback (KK-Mac)

Install (one-time, needs the chaba checkout at
`~/CascadeProjects/chaba` current):

```bash
cp scripts/ops/net.adanest.kk-llm-worker.plist ~/Library/LaunchAgents/
launchctl bootout gui/$(id -u)/net.adanest.kk-llm-worker 2>/dev/null
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/net.adanest.kk-llm-worker.plist
launchctl print gui/$(id -u)/net.adanest.kk-llm-worker | head
```

Rollback to the previous generic worker (the plist `.bak` convention —
keep a timestamped copy before every swap):

```bash
cp ~/Library/LaunchAgents/net.adanest.kk-llm-worker.plist \
   ~/Library/LaunchAgents/net.adanest.kk-llm-worker.plist.bak-$(date +%Y%m%d)
# restore the prior plist, then:
launchctl bootout gui/$(id -u)/net.adanest.kk-llm-worker
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/net.adanest.kk-llm-worker.plist
```

Instant drain without touching launchd: `touch ~/.cache/kk-llm-worker.drain`
(remove to resume). Queue-side stop: `DEVNEST_KK_MAC_ENABLED=false` in the
producer/broker unit env holds new intake while the worker drains.

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

The dedicated lane worker (`kk_mac_lane_worker.py`), the capacity-aware
producer, broker, and report feed are built and the 10-package soaks
passed. Remaining before automatic JEV promotion: swap the live
LaunchAgent onto the lane worker (plist in `scripts/ops/`), one fresh
supervised soak against the lane worker, and the weekly-review policy
sign-off.
