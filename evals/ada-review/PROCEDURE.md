# Ada result-review pilot — usage

Card: `ada-opencode-result-review-pilot` (ADA-1041). Evaluation-only:
Ada reviews OpenCode result bundles; she never executes, approves,
merges, deploys, or mutates board state. Deterministic tests/verifiers
remain hard gates.

## Pieces

- `scripts/devnest/ada_result_review.py` — `bundle` / `review` / `eval`
- `schemas/ada-review-bundle.schema.json` — allowlisted bundle contract
- `schemas/ada-opencode-review.schema.json` — verdict contract
  (`pass|fail|needs_human` + findings + evidence_refs)
- `evals/ada-review/cases/<case>/` — frozen corpus: `bundle.json`
  (sanitized snapshot), `artifact.json`, `expected.yml` (held-out
  label — never shown to the reviewer), `request.md`,
  `review-replay.json` (offline oracle for plumbing tests)
- `evals/ada-review/reports/` — eval outputs (md + json, raw replies
  under `raw-*/`)

## Commands

```bash
# assemble a bundle from a run dir (never includes raw trace/verifier
# source/held-out labels)
python3 scripts/devnest/ada_result_review.py bundle \
    evals/opencode-lane/runs/<job>-<ts> --out /tmp/bundle.json

# one review (litellm = model baseline; ada-ws = live Ada, gated)
python3 scripts/devnest/ada_result_review.py review /tmp/bundle.json \
    --backend litellm --model gemini-3.5-flash-lite
ADA_REVIEW_ALLOW_LIVE=1 python3 scripts/devnest/ada_result_review.py \
    review bundle.json --backend ada-ws --ada-url http://127.0.0.1:8005

# shadow eval over the frozen corpus
python3 scripts/devnest/ada_result_review.py eval --backend replay
python3 scripts/devnest/ada_result_review.py eval --backend litellm \
    --model chat
```

Backends: `litellm` (OpenAI-compatible, key from
`~/.config/secrets/litellm-chaba.env` or `LITELLM_KEY`), `ada-ws`
(WS `mode=text` session; requires `ADA_REVIEW_ALLOW_LIVE=1`, lane must
be reachable — ada-dev :8005 is loopback on idc03), `replay` (canned
`review-replay.json`), `stub` (plumbing smoke).

## Metrics emitted per eval run

verdict distribution, critical-defect recall, needs_human escape count,
false-positive rate on clean cases, deterministic-gate disagreement,
evidence-citation quality (ref resolution into the bundle, findings
with refs), latency p50, cost. Full reviews are embedded in the report
JSON — that report path is the card `result_ref`.

## Boundaries

- Reviews are evidence for humans, not approvals. No card mutation,
  merge, deploy, or executor-path change lives here.
- `ada` stays out of `ada_job_envelope.EXECUTORS` — this is a review
  plane, not an `executor=ada` lane.
- Live `ada-ws` activation and any Ada tool/DevTeam playbook use
  require review before dispatch (card spec).
