---
category: operations
type: standard
status: defined
---

# Ada Development-Control-Plane Job Envelope

## Purpose

ADA-1010 defines one contract shared by Ada, Node-RED, OpenCode, Cline, and DevNest. Ada may understand intent and prepare the envelope; an explicitly declared executor performs work; an independent verifier produces evidence; Tony retains merge/deploy and self-modification approval.

## Required envelope

The JSON Schema is `schemas/ada-job-envelope.schema.json`. Required fields are:

```text
job_id, card_id, project, repo, worktree, task_class,
objective, requirements, acceptance_criteria, executor, model,
target_host, allowed_paths, input_artifacts, output_artifacts,
verify, approval_required, timeout_s, idempotency_key, state
```

Known executor values are `opencode`, `devin`, `script`, `manual`, and `kk_mac_local`. Unknown executors and unknown envelope fields fail closed; no silent fallback or schema drift is allowed.

## Lifecycle

```text
draft -> ready -> claimed -> running -> verifying
      -> review -> approved -> merged -> done

Failure/recovery states are explicit: `failed`, `stalled`, and `cancelled`.
A failed job may return to `ready` for a bounded retry; a stalled job may
return to `claimed` after reconciliation; cancelled is terminal.
```

A heartbeat is progress evidence, not completion. `done` requires the declared artifact bundle and an independent verifier receipt.

## Result bundle

Every execution must retain:

```text
result.json
summary.md
diff.patch
tests.json
logs/
artifacts/
```

The validator is `scripts/board/ada_job_envelope.py`; its tests are `tests/board/test_ada_job_envelope.py`.

## Separation of duties

Ada must not approve her own implementation. Planning and handoff previews are read-only. Merge, deploy, credentials, destructive actions, and changes to Ada's own runtime require a separate approval gate.
