---
category: infrastructure
status: verified
created: 2026-11-25
source: auto-kb
title: "opencode-lane Gate Runbook (S1 quota, heartbeat, scope violations)"
tags: [opencode, lane, gate, quota, heartbeat, evaluation]
---

# opencode-lane Gate Runbook

Operational reference for the opencode-lane stage gate (S0–S5), focusing on S1 supervised read-only canary runs.

## Stage Model (lane_gate.py)

| Stage | Description | Quota | Concurrency | Supervised |
|-------|-------------|-------|-------------|------------|
| S0    | smoke probe | 5 | 1 | no |
| **S1** | supervised read-only report canary | **15** (was 3) | 1 | **yes** |
| S2    | ... | 5 | 1 | no |
| S3    | ... | 12 | 2 | no |
| S4    | branch code / artifact write | — | 1 | yes |
| S5    | production deploy | — | 1 | yes |

**S1 quota** (`STAGES["S1"]["quota"]`): number of admitted runs before `quota_exceeded` denial. Stored in `~/.local/state/opencode-lane/stage.json` → `jobs_completed.S1`.

## Heartbeat Requirement (Supervised Stages)

Supervised stages (S1, S4, S5) require a **fresh heartbeat file** before admission:

- Path: `~/.local/state/opencode-lane/heartbeat-<job_id>.json`
- Content: `{"job": "<job_id>", "at": "<ISO8601 timestamp>"}`
- Stale threshold: 300s (5 min) — checked by `_heartbeat_age_s()` in `lane_gate.py`
- Written automatically by `opencode_profiles.py` at run start (line ~1200)
- **Manual refresh** if retry needed:
  ```bash
  python3 -c '
  import json
  from datetime import datetime, timezone
  p = "/home/tony/.local/state/opencode-lane/heartbeat-<job_id>.json"
  open(p, "w").write(json.dumps({"job": "<job_id>", "at": datetime.now(timezone.utc).astimezone().isoformat()}))
  '
  ```

## Quota Management

| Action | How | When |
|--------|-----|------|
| **Raise quota (recommended)** | Edit `lane_gate.py`: `STAGES["S1"]["quota"] = <n>`; add comment with date/ticket | Need more runs, preserve history |
| **Reset ledger (avoid)** | Zero `jobs_completed["S1"]` in `stage.json` | Only if explicitly approved; falsifies promotion evidence |
| **Document gap** | Record in job YAML or SSOT: "S1 quota exhausted (N/N), gate run deferred" | When gate run not needed immediately |

## Gate Admission Checks (lane_gate.py)

| Check | Denial Reason | Notes |
|-------|---------------|-------|
| Provider probe | `failed_provider:<provider>` | Net connectivity to required providers |
| Concurrency cap | `concurrency_cap:<n>=<cap>` | Per-stage limit |
| Heartbeat (supervised) | `stale_heartbeat` | Age > 300s or missing |
| Model allowlist (profile) | `profile_denied_model:<model>` | Profile `allowed` list |
| Provider allowlist (profile) | `profile_denied_provider:<provider>` | Profile `providers` list |
| Quota | `quota_exceeded:S1 did <done>/<quota>` | Stage-specific |
| Rollback plan (S4/S5) | `missing_rollback:<kind>` | Required for mutating stages |

## Run Output Interpretation

| Field | Meaning |
|-------|---------|
| `admit: true` | Gate passed; run executed |
| `verdict: fail` + `artifact_landed: false` | Run completed but no output artifact |
| `denials: []` | No tool-call denials (read-only clean) |
| `mutating: []` | No mutating tool calls |
| `scope_violations: [...]` | **Read-only profile** flagged paths outside allowlist — expected for ops-readonly; not a gate failure |
| `verifier_peeks: []` | No independent verifier peeks (S1 has none) |

## Common Patterns

- **Model reference format**: `litellm/<model-id>` in job YAML → opencode resolves via `provider.litellm` in `opencode.json`
- **Virtual key selection**: `litellm_key()` in `opencode_profiles.py` tries `LITELLM_KEY`, `LITELLM_KEY_BENCH`, `LITELLM_KEY_CHABA`, `LITELLM_KEY_ADA` (env + `~/.config/secrets/*.env`)
- **Retry budget**: `envelope.escalation.max_retries` (ceiling-checked against profile)

## Files

- `scripts/devnest/lane_gate.py` — stage definitions, admission logic
- `scripts/devnest/opencode_profiles.py` — profile loading, run orchestration, heartbeat/inflight
- `evals/opencode-lane/profiles/<name>/profile.yml` — model/provider allowlists per profile
- `evals/opencode-lane/jobs/*.yaml` — gate test jobs
- `~/.local/state/opencode-lane/stage.json` — persistent ledger (jobs_completed, history)
- `~/.local/state/opencode-lane/heartbeat-*.json` — per-job heartbeat files
- `~/.config/opencode/opencode.json` — provider + model definitions

## Post-merge verification (2026-11-27)

After PR #226 squash-merge (`2f53b179ab`), the offload was re-verified live:

- **Routing**: `lane_model("free_lane", "opencode")` -> `litellm/agent-local`; `model_valid_for_executor(..., "opencode") == True`. 72 lane/dispatch tests pass (`test_lane_envelope_staging`, `test_runner_agent_lane`, `test_dispatch_runner_resilience`).
- **Prefix resolution**: opencode takes `litellm/` as its provider selector (`provider.litellm` -> `http://100.102.134.91:4000/v1`) and sends the bare model id `agent-local` to the gateway. The gateway allowlist therefore needs `agent-local` (present), not `litellm/agent-local`.
- **403 triage**: one SpendLog row (`2026-11-26T17:46:00Z`, key alias `chaba`) shows `403_MODEL_ACCESS_DENIED` for `litellm/agent-local`. This was the pre-allowlist-fix attempt; the same key's live `/key/info` now lists `agent-local`. Not a post-merge regression.
- **Live POST**: `agent-local` chat completion returns HTTP 200 / `PONG` in ~3s; logged under model_group `gemini-3.5-flash-lite-free` (free route).
- **Budget**: pre-fix failures (2026-11-25) logged paid `gemini-3.5-flash-lite` under group `agent-local` as 503 failures; no paid spend on successful agent-local legs. Proxy-wide cap is $120 (key cap $40).

## Related

- KB: free_lane Offload Architecture (agent-local chain)
- OPS-1363 (kk-mac offload repoint gate run)