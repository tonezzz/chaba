# Video queue claim-lifecycle procedure

## Queue states

Every video package must be classifiable as exactly one of:

```text
queued       no claim, no done/failed marker
running      fresh claim owned by a live worker
stale        claim older than the lease TTL without a live worker
done         durable artifact and verifier/done marker
failed       terminal failure recorded
retired      intentionally removed from dispatch without deleting history
```

`queued/other` is not a valid final status. It must be resolved into a
support package, canonical render package, historical package, or retired
package.

## Lease and heartbeat

The default video claim TTL is two hours. A worker that runs longer must
refresh a heartbeat containing:

```text
project_id
package
worker
pid/job_id
phase
started_at
heartbeat_at
```

The status tool may report stale claims, but it must not delete or release
them automatically.

## Reconciliation procedure

1. Inventory both video roots:
   - `gdrive:ada-nest-kk-mac-video-pilot`
   - `gdrive:ada-nest`
2. Read package manifest, claim, done/failed markers, and artifact paths.
3. Check the worker host and job/process evidence.
4. Classify the package:

```text
done/failed artifact present -> close history; never rerun automatically
fresh worker evidence        -> running
old probe/support package    -> retired
canonical current manifest   -> release and requeue after safety check
unknown                      -> hold for review
```

5. Write a durable reconciliation record before changing queue state.
6. For a stale canonical package, remove only its claim marker and leave the
   package manifest/artifacts intact; the next single approved worker may
   claim it.
7. For historical/support work, write a `retired` marker with the reason and
   preserve the original claim and artifacts in history. Do not rerun it.

## Canonical render rule

Each project has one active render manifest:

```text
project_id
manifest_version
approved_shots
source_hash
renderer/model
output_root
qc_contract
```

Only packages referenced by that manifest may be dispatched for the current
final cut. Probes, preflights, old variants, and support packages are never
silently promoted into final rendering.

## Efficiency and safety

```text
one writer per queue
one video runner per host
MLX concurrency = 1
Colab concurrency = 1 managed runner
status scans are read-only
stale cleanup is explicit and auditable
```

Measure:

```text
fresh claim latency
stale-claim count/age
queue wait
render wall time
artifact/QC pass rate
rerun rate
duplicate claim attempts
```

The queue is healthy only when stale claims trend to zero and every queued
package has a declared role. This procedure is used by OPS-1042.
