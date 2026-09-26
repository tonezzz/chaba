# Ada Evals — job-report dispatch design

Status: **phase 1 specced + patch verified, not yet applied/deployed** (2026-09-26)
Origin: session `artistic-pleasure` ("Job docs"), resumed by dispatch session.
Canonical copy: this file. Working copy: `ada-pi/docs/eval-jobs.md`
(untracked in ada-pi as of 2026-09-26 — commit it when phase 1 lands).

## Problem

Scenario runs today are `systemctl start ada-scenario-{smoke,full}` on idc01 —
fire-and-forget: no handle to check progress, no structured spec, no metrics
for before/after comparison, no per-run A/B lever for config like session
prime (`ADA_SESSION_PRIME` is a server env — cannot toggle per run).

## Proposal (user's model, agreed)

Job docs in MDDB collection `ada-eval-jobs`. A requester (Devin session, Ada
tool, or human) writes the job **before** dispatch — the doc is simultaneously
the spec, the live status, and the result record. A dispatcher service on
idc01 polls for queued jobs, runs them in the existing
`ada-scenario-runner` container, and keeps updating the doc while processing.
Every update is an MDDB revision — the job's timeline is free.

## Lifecycle

```
requester writes:  status=queued, spec={...}
dispatcher claims: status=running, claimed_by, heartbeat_at
per-scenario:      progress={done,total,current}, heartbeat_at refresh
finish:            status=done|failed, result={verdicts, metrics},
                   links to per-scenario reports in ada-ha-scenario-reports
stale heartbeat:   sweeper marks running→failed (stale) after ~10 min
cancel:            requester writes status=cancel → dispatcher kills
                   between scenarios
```

## Job doc schema (`ada-eval-jobs/<slug>-<ts>`)

```yaml
meta:
  kind: eval-job
  status: queued|running|done|failed|cancel
  requested_by: devin-session|ada-voice|manual
  reason: free text (e.g. "prime A/B for tv_power")
  spec_tier: smoke|full|bench
  spec_scenarios: [tv_power, doc_recall]   # empty = whole tier
  spec_repeat: 3                          # runs per arm (LLM variance)
  spec_arms: [prime-on, prime-off]        # maps to ws ?no_prime=0/1
  progress_done / progress_total / progress_current
  heartbeat_at
  result_verdicts, result_metrics         # summary; detail in report docs
```

## Dispatcher — `ada-evald.service` (idc01, user unit, phase 2)

- ~100-line python loop: `search_documents(ada-eval-jobs,
  filter_meta={status:queued})` every 10–15 s.
- Claim = write `status:running` + `claimed_by`. **Single-worker by design** —
  scenarios actuate the shared TV/plug; parallelism would fight hardware.
- Runs `podman run ada-scenario-runner --job <key>`; the runner reads its
  spec back from the doc (decoupled: no env plumbing).
- Whitelist-only spec fields; never interpolate doc content into shell —
  a job doc is a write vector.
- Rejects malformed specs → `status:failed, error=...` immediately.

## Runner additions (`scenario-live.py` / `scenario-report.py`)

- `--job <key>`: per-scenario-boundary job doc updates (progress + heartbeat).
- `--repeat N`: repeat each scenario; verdict = majority, metrics = mean/min/max.
- Per-turn metrics into report docs: `tool_calls[]`, `calls_count`,
  `turn_latency_s`, `in_tokens`, `out_tokens`.
- Bench arms → `spec_arms` maps each arm to ws params (e.g. `no_prime`).

## Backend addition

- `?no_prime=1` ws query param honored at **both** prime sites in
  `pwa_server.py`: `_prime_session_task` (session start, ~line 394) **and**
  the provider-reconnect re-prime (`if not handle:` ~line 729). The resume
  review caught that gating only the first site leaks prime into the off-arm
  whenever a Gemini session reconnects mid-run — the shipped patch covers
  both. Mirrors the existing `simulate_unknown_speaker` test hook.

## Completion surface

- On `done`: `chaba_event` log → `/chaba-admin/events` ("eval job tv_power:
  pass; prime-off arm +1.4 tool calls/turn") — reuses a surface already watched.
- Phase 3: `ada_eval_run` tool so voice can dispatch + report
  ("Ada, run the smoke evals" → she announces the verdict when done).

## Phases

1. `no_prime` param + metrics capture in `scenario-live.py` + `ada-eval-jobs`
   collection — manually-written job docs, run locally for first data.
   **← current: patch ready, see below**
2. `ada-evald` dispatcher + stale sweeper + chaba event on done.
3. `ada_eval_run` voice tool + cancel support.
4. Nightly timer (`ada-eval-smoke.timer`) once the suite is green.

## Phase 1 — ready-to-apply patch

`docs/kb/ada-eval-jobs-phase1.patch` (verified `git apply --check` clean
against ada-pi HEAD `607035c`, all four files `py_compile` clean, `--param`
shows in `--help`):

| File | Change |
|---|---|
| `backend/realtime_provider.py` | `response_completed` event now carries `duration_ms`, `in_tokens_total`, `out_tokens_total` (cumulative per provider session) |
| `pwa_server.py` | `?no_prime=1` skips session prime in `_prime_session_task` **and** the provider-reconnect re-prime |
| `scripts/scenario-live.py` | `--param K=V` (repeatable, merged after scenario params); per-turn `in_tokens`/`out_tokens`/`latency_s`/`n_tools` in `turn_log`; run-level `totals` block in `--events-json` |
| `scripts/scenario-report.py` | `tool_calls`, `in_tokens`, `out_tokens` roll up into report meta |

Token accounting: totals are cumulative per provider session; the runner
treats `tot_in < prev_in` **or** a `live_reconnecting` event in the turn as a
counter reset, diffs per turn, and sums deltas into `totals` (correct across
mid-run session swaps — an improvement over the original spec which would
have under-reported after reconnects).

### Apply + first A/B (needs a mode with write/exec on ada-pi + idc01)

```bash
cd ~/CascadeProjects/ada-pi
git apply ~/CascadeProjects/chaba/docs/kb/ada-eval-jobs-phase1.patch
python3 -m py_compile backend/realtime_provider.py pwa_server.py \
    scripts/scenario-live.py scripts/scenario-report.py
# commit on a branch, deploy to idc01, restart ada-ha-tony, then:

# off arm (no prime)
python3 scripts/scenario-live.py tests/scenarios-live/tv_power.yaml \
    --api-key "$ADA_API_KEY" --param no_prime=1 \
    --events-json /tmp/tvpower-noprime.json -v

# on arm
python3 scripts/scenario-live.py tests/scenarios-live/tv_power.yaml \
    --api-key "$ADA_API_KEY" \
    --events-json /tmp/tvpower-prime.json -v
```

First job doc (write to `ada-eval-jobs` on idc01 MDDB,
`http://100.74.146.0:11023/v1`) — intentionally **not** written by the resume
session: a `queued` doc becomes a live trigger the moment `ada-evald` ships,
and `tv_power` actuates the real TV plug. Write it as part of the run that
deploys phase 1:

```json
{"collection": "ada-eval-jobs", "key": "eval/tv-power-prime-ab-20260925",
 "contentMd": "# tv_power prime A/B\nspec: scenarios=[tv_power], repeat=1, arms=[prime-on, prime-off(no_prime=1)]\n\n## Result\n(filled after run — per-arm tool_calls, latency, tokens, verdict)",
 "meta": {"kind": ["eval-job"], "status": ["queued"],
          "scenarios": ["tv_power"], "requested_by": ["devin"],
          "last_verified": ["2026-09-25"], "valid_until": ["2026-10-09"]}}
```

## Scenario runner baseline (as of 2026-09-25)

- `ada-scenario-smoke`: 4 pass / 3 fail; `ada-scenario-full`: 12 pass /
  9 fail / 2 flaky of 23 — pre-existing fails, unrelated to evals work.
- No timers — manual/on-demand only; exit code 1 just means ≥1 scenario failed.
- Reports already persist to MDDB `ada-ha-scenario-reports`.
- Umbrella term: **evals** covers correctness scenarios + metric benchmarks;
  keep `ada-scenario-runner` image, add `ada-eval-bench.service` (same image,
  `--bench --repeat 3`) when phase 2 lands.

## Open questions

- Repeat default: 3 per arm? (cost: each turn = real Gemini Live tokens)
- Should `bench` tier scenarios get a `budget` cap on tool calls?
- Job doc TTL — 30d in `ada-eval-jobs`, permanent summary in
  `ada-ha-scenario-reports`?
