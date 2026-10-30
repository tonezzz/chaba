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

### Verifier rule

`expect` must contain a meaningful independent check. Do not submit
`expect: {}` for a result that will be described as verified: the current
worker then proves only that the model returned non-empty text. For summaries,
include source-backed literal facts and keep the original source path with the
result. Literal fact checks prove presence, not absence of hallucinations, so
report summaries remain drafts for human review unless a stronger
source-grounded verifier is available.

### Fast submission (skip the timer wait)

The normal cadence is report feed every 15 minutes and broker/producer every
5 minutes. To send one bounded package immediately, write the normalized task
to the shared DevNest inbox and start the existing one-shot services in order.
This skips timer delay only; it does not bypass admission, queue-depth, task
class, or verification gates.

1. Prepare a unique, lowercase task slug and a JSON task file. Example shape
   (replace every placeholder before submitting):

   ```json
   {
     "task_id": "report-review-20261030-a1b2c3",
     "lane": "kk_mac_local",
     "task_class": "summary",
     "model": "qwen3:8b",
     "prompt": "Summarize this source for an operator. Include only facts present in the supplied evidence. Evidence: ...",
     "expect": {
       "facts": ["a short literal fact copied from the evidence"]
     },
     "source": "reports/example-report.json"
   }
   ```

2. Validate and submit it from a machine with the `tony-dell` SSH alias and
   local task file:

   ```bash
   set -euo pipefail
   TASK_ID=report-review-20261030-a1b2c3
   TASK_FILE="/tmp/${TASK_ID}.json"
   [[ "$TASK_ID" =~ ^[a-z0-9][a-z0-9-]{1,60}$ ]]
   python3 -m json.tool "$TASK_FILE" >/dev/null
   if ssh tony-dell "rclone lsf gdrive:ada-nest-devnest/inbox/" | grep -Fxq "${TASK_ID}.json"; then
     echo "task ID already exists; inspect it instead of resubmitting" >&2
     exit 1
   fi
   if ssh tony-dell "rclone lsf gdrive:ada-nest-kk-llm/packs --max-depth 1" | grep -Fxq "kk-mac-task-${TASK_ID}/"; then
     echo "task pack already exists; inspect it instead of restaging" >&2
     exit 1
   fi
   ssh tony-dell "rclone rcat gdrive:ada-nest-devnest/inbox/${TASK_ID}.json" < "$TASK_FILE"
   ```

   If local temp storage is quota-limited, run the same task-ID collision
   checks above, then keep the JSON in memory and stream it directly. Validate
   before connecting so a failed generator cannot create an empty inbox object:

   ```bash
   TASK_JSON="$(python3 - "$TASK_ID" <<'PY'
   import json, sys
   task = {
       "task_id": sys.argv[1],
       "lane": "kk_mac_local",
       "task_class": "structured_extract",
       "model": "qwen3:8b",
       "format": "json",
       "prompt": "Extract the requested source-backed fields as JSON: ...",
       "expect": {
           "required_keys": ["field_a"],
           "facts": ["exact phrase copied from the evidence"]
       },
       "source": "reports/example-report.json"
   }
   assert task["prompt"] and task["expect"]["facts"]
   print(json.dumps(task, ensure_ascii=False))
   PY
   )"
   python3 -c 'import json,sys; json.loads(sys.argv[1])' "$TASK_JSON"
   printf '%s' "$TASK_JSON" | ssh tony-dell "rclone rcat gdrive:ada-nest-devnest/inbox/${TASK_ID}.json"
   ```

3. Kick the broker, then the KK producer. They are declared systemd user
   oneshots on `tony-dell`; the broker applies admission and queue-capacity
   gates, then the producer stages an accepted inbox item as a pack:

   ```bash
   ssh tony-dell 'systemctl --user start devnest-capacity-broker.service'
   ssh tony-dell 'systemctl --user start jevnest-kk-mac-capacity-producer.service'
   ```

4. For a report that should be discovered by the allowlisted report feed
   instead of manually supplied, kick the feed first, then run the same
   broker and producer commands:

   ```bash
   ssh tony-dell 'systemctl --user start devnest-report-feed.service'
   ssh tony-dell 'systemctl --user start devnest-capacity-broker.service'
   ssh tony-dell 'systemctl --user start jevnest-kk-mac-capacity-producer.service'
   ```

5. Verify the consumer artifact, not just the successful service exit:

   ```bash
   PACK="gdrive:ada-nest-kk-llm/packs/kk-mac-task-${TASK_ID}"
   rclone cat "${PACK}/done"
   rclone cat "${PACK}/out/result.json"
   ```

   Require a matching `done` marker and a passing independent check in the
   result. If `failed` exists, inspect its reason. If only `claim/` exists,
   wait and inspect the same task; do not submit a duplicate.

Guardrails:

- Do not write directly into the KK pack tree or create claim/done markers by
  hand; the broker and producer own routing and pack staging.
- Reuse the same `task_id` when retrying an unchanged task. The broker routed
  marker and producer pack-name check make submission idempotent.
- If the broker reports `kk_capacity` or admission is ineligible, leave the
  task in the shared inbox. Do not raise the depth cap, start a second worker,
  or bypass the owner/load gate.
- `verified: true` is only as strong as the declared `expect` checks. Do not
  treat a non-empty summary as factually verified or publish it automatically.

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

## Current status and next step

The KK-Mac worker, capacity producer, shared broker, and allowlisted report
feed are deployed. The 10-package semantic soak passed 10/10 JSON/schema/fact
checks. A post-reenable report-feed canary drained real packages, but a sampled
`reports/LOG_CHECK.json` summary claimed services were stable even though its
source only contained a check-only inventory and no runtime health results.
That package used `expect: {}`, so its `verified` flag meant only
`response_nonempty`.

Use the fast path above to remove timer delay, but keep report summaries as
human-review drafts until their factual verifier is strengthened. Automatic
JEV promotion remains gated on the supervised probe artifact being landed and
verified, plus policy review of the report-summary verifier.

The immediate path was exercised on 2026-10-30 with
`decision-arena-extract-20261030-2114`, a structured extraction from
`reports/2026-10-25-decision-arena-50.md`. The pack reached the KK queue,
completed with a `done` marker, and passed JSON parsing, required-key, and
literal-fact checks in 2.525 seconds. This verifies the one-shot submit path;
it does not upgrade empty-`expect` report summaries to factually verified.
