# Job-Package Status Lifecycle & Storage Standard

## 1. Job Statuses (JOB_STATUSES enum)
| Status   | Meaning (per `scripts/board/board-api.py`) |
|----------|-------------------------------------------|
| **queued**   | Job has been submitted to the queue but not yet claimed. |
| **claimed**  | A host has taken ownership; the job is now **running**. |
| **running**  | The job is actively executing on the assigned host. |
| **done**     | The job completed successfully; result is available. |
| **failed**   | The job terminated with an error; result may be recorded. |
| **stalled**  | The job is not progressing (e.g., waiting on external resources). |
| **cancelled**| The job was explicitly aborted before completion. |

## 2. Lifecycle Transitions & Who Writes Them
| From → To      | Trigger / Action                              | Writer (who updates the state)                              |
|----------------|-----------------------------------------------|-------------------------------------------------------------|
| **queued → claimed** | `do_claim` (host claims the queued job)      | **claiming host** (via `do_claim`) – sets `action.status=running`, column=`doing`. |
| **claimed → running** | Implicit after claim; the job’s runner starts work. | **runner** (via the job’s execution code) – no board-API write; the board reflects the running state via `action.status=running`. |
| **running → done**   | Pack runner finishes successfully (`do_finish` with `ok=True`). | **runner** (via `do_finish`) – updates `status=done`, column=`review`, writes `result_ref` and any `error` in the WP `nest_job` CPT meta. |
| **running → failed** | Pack runner reports failure (`do_finish` with `ok=False`). | **runner** (via `do_finish`) – sets `status=failed`, leaves column unchanged, stores error in meta. |
| **running → stalled**| External condition stops progress (e.g., missing resource). | **any actor** (via `do_publish` → `_pub_job_send` → `do_job` with `status=stalled`). |
| **running → cancelled**| Explicit cancellation request (`do_action` “cancel” or similar). | **claiming host** (via `do_action` “cancel”) – sets `status=cancelled`, column unchanged, writes comms. |
| **done → (any)**      | Manual re-queue or re-spawn (e.g., report-page respawn). | **board-api** (`do_create` with `action.type=dispatch`) – re-queues the card, resets `status=queued`. |
| **failed → done** (post-mortem) | Human verification that the failure is resolved. | **human** (via `do_action` “close” after verification) – sets `status=done`, column=`review`, clears error. |

## 3. State Mirroring
| Artifact | Where State Lives | How It Is Updated |
|----------|-------------------|-------------------|
| **WP `nest_job` CPT** | WordPress post (`/wp/v2/nest_job`) stored in the `meta` field. | `do_job` (called from `/job` or `_pub_job_send`) upserts the CPT, writes `status`, `result_ref`, `error`, `updated`, and appends to `comms` JSON log. |
| **Kanban column** | Card YAML (`docs/ssot/kanban/cards/<id>.yml`) under the `column` key. | `do_action` (queue, claim, close, move, finish) updates `column` to match the current `action.status` (e.g., `do_claim` → `column=doing`, `do_finish` → `column=review` on success). |
| **PublicationEvent** | The canonical JSON payload posted to `/publish`. | `do_publish` validates and routes the event; for `progress`/`milestone`/`alert` it calls `_pub_job_send`, which in turn calls `do_job` (the same upsert logic as direct `/job`). |
| **Result Ref / Artifact** | Stored in the `result_ref` meta key of the `nest_job` CPT (and referenced by the runner). The actual artifact (e.g., log files, output) is expected to be reachable via that reference; the board-API never writes the artifact itself. | `do_finish` writes `result_ref` into the CPT meta; the runner may also place the artifact in a known location (e.g., a shared volume) and record the path in `result_ref`. |

## 4. Who Writes Each Transition
- **Queue-mgr** (queue-mgr daemon) – calls `do_action` “queue” → creates a card with `status=queued`; later `do_claim` (host claim) → sets `status=running` and `column=doing`.
- **Pack runner** (e.g., `devin-dispatch` or systemd-run task) – executes the job; on success calls `do_finish` → `status=done`, `column=review`, writes `result_ref`; on failure calls `do_finish` with `ok=False` → `status=failed`.
- **Ada / Chaba** – can raise `request` or `comment` events that trigger `do_publish` → `_pub_job_send` → `do_job` to update status (e.g., `stalled` via a progress event).
- **System sweeper** (`kanban-commit.timer`) – periodically reconciles any out-of-sync cards (autostash-eaten edits) but does not alter the logical status; it only ensures the card YAML is committed.

## 5. Enforcement at the write door (OPS-0923)

The transition table above is enforced in code, not just documented —
`do_job` in `scripts/board/board-api.py` rejects violations with HTTP
400 before any WP write:

- **Transition guard** — `JOB_TRANSITIONS` maps each prior status to
  its legal successors. Same-status rewrites and writes carrying no
  `status` (comms-only updates) always pass; a prior status outside
  the map (legacy/garbage meta) imposes no constraint. Terminal
  `done`/`cancelled` exit only via `queued` (explicit requeue) or
  `failed` (honest false-done correction) — never a silent
  resurrection into claimed/running.
- **Terminal-done gate** — `status=done` requires BOTH:
  1. `result_ref` — a durable pointer to the result (body, stored
     meta, or `meta.result_ref` all count), and
  2. verified artifact evidence — `evidence[]` refs, `verified:true`,
     `artifact_verified`, or `confidence=verified` (body or
     `body.meta`). A bare `status=done` is rejected.
- **Evidence persistence** — accepted `evidence[]` refs are joined
  into `meta.evidence` (≤300 chars) and `meta.artifact_verified=true`
  is stamped when a verified signal was supplied, so auditors and the
  reconciler can see the proof without replaying comms.

`/publish` honors the same contract through the job sink: a
`PublicationEvent` only reaches `do_job` when it carries an explicit
`job` ref (card/project-scoped events never mint `nest_job` posts),
and `kind=milestone` no longer implies `status=done` — milestones are
checkpoints. `meta.job_status` is the explicit override; `progress`→
`running` and `alert`→`stalled` remain liveness hints. A `done`
assertion missing evidence surfaces as a per-sink `skipped` receipt
(`job status rejected: …`) — never retried through the outbox, while
sibling sinks still deliver.

`scripts/ops/nest-job-reconcile.py` is the read-only cross-check: it
compares `nest_job` meta against pack `done`/`claim/` markers,
`queue/packs-index`, and `queue/lease`, and reports drift
(`DONE-NO-RESULT-REF`, `DONE-UNVERIFIED`, `DONE-NO-PACK-MARKER`,
`PACK-DONE-JOB-NOT-DONE`, `CANCELLED-LINGER-CLAIM`, …). It never
mutates — acting on a finding is a separate gated decision.

## 6. Result Ref / Artifact Storage Convention
- The **canonical reference** for the job’s result is the `result_ref` field stored in the `nest_job` CPT meta (key `"result_ref"`).  
- The **artifact** (log files, reports, outputs) must be reachable via that reference (e.g., a path, URL, or internal storage identifier).  
- The board-API never writes the artifact directly; it only records the reference. Runners are responsible for persisting the artifact and updating `result_ref` if the location changes.  
- Errors are stored in the `error` meta key (string, max 300 chars) and are also surfaced via the `failed` status.

## 7. Summary
- **Status flow**: `queued → claimed → running → (done | failed | stalled | cancelled)`.  
- **Who writes**: queue-mgr (claim), pack runner (finish), any actor (progress/alert events), human verification (post-failure close).  
- **State mirrors**: WP `nest_job` CPT meta holds the authoritative status, `result_ref`, and error; the kanban column reflects the same logical state; the `PublicationEvent` is the source of truth for fan-out to other sinks (Telegram, JSON ledger, etc.).  
- **Artifact storage**: `result_ref` points to where the actual result lives; the board-API never stores the artifact itself.  

*All seven JOB_STATUSES values are explicitly covered, and the lifecycle, writers, mirroring locations, and storage convention are documented per the code contracts.*