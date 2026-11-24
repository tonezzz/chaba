# Jack LLM-stack agent evaluation — OpenCode vs Cline

Card: `jack-llm-stack-agent-eval` · Date: 2026-11-24 ·
Runner: devin-dispatch on tony-macbook · Mode: S0 shadow/replay → S1 supervised

Matched benchmark per lesson `jack-llm-stack-agent-evaluation`
(post 3103): both agents receive the **identical** bounded brief
(`brief/task-brief.md`) — design, configure, test, and document a
disposable Jack LLM stack (local Ollama model + LiteLLM-compatible
routing + OpenCode provider config + health checks + secret
placeholders + resource limits + rollback + operator runbook) — inside a
fresh isolated git repo, on a host with **no container runtime** (mock
deployment required). No production DNS/Cloudflare/credentials/Ada-Devin
memory/household HA/external spend.

## Arms (matched conditions)

| | OpenCode arm | Cline arm |
|---|---|---|
| CLI | opencode 1.19.4 | cline 3.0.75 (npm, isolated `--data-dir`) |
| Model | `bench` → qwen2.5:32b on kk-mac via LiteLLM ($0) | same |
| Mode | headless `run --format json`, auto-approve | one-shot `--json` yolo |
| Workspace | `arms/opencode/` (fresh git repo) | `arms/cline/` (fresh git repo) |
| State | `arms/.opencode.home/` (outside repo) | `arms/.cline-data-cline/` (outside repo) |

Sequential execution to keep the shared local-model backend unloaded
between arms (matched wall-time conditions).

## Harness

- `harness/verify_stack.py` — **independent** deterministic verifier
  (written before the arms ran): committed-artifact, per-spec artifact
  checks, dynamic `verify.sh` execution, secret/scope safety scan.
- `harness/run_arm.sh` — per-arm runner: epoch timing, NDJSON event
  capture, contained HOME/data dirs.
- `harness/opencode.eval.json` — eval-only provider config (never the
  agents' artifact).
- `fixtures/reference/` — compliant reference stack (S0 positive).
- `fixtures/bad/` — non-compliant fixture with fake secret + prod refs
  (S0 negative).

## Stage log

- **S0 shadow/replay** — verifier run against fixtures:
  `results/s0-reference-verifier.json` PASS (all checks),
  `results/s0-bad-verifier.json` FAIL (17 findings incl. secret +
  forbidden-ref violations). Harness discriminates.
- **S1 supervised** — one build per arm under devin supervision;
  `results/<arm>/run.json` wall time, `events.jsonl` agent stream,
  `verifier.json` independent result, `safety.json` ledger.
- **S2** — not entered. Unattended routing stays gated by the existing
  opencode-lane evidence gate (lane at S0 after 2026-11-12 stor-01
  rollback; `opencode-lane-regraduation` owns the climb). This eval
  produces evidence only; it enables nothing.

## Results

**Verdict: Cline wins this bounded build.** Both arms PASS the
independent verifier + their own `verify.sh` + idempotent rollback +
clean safety scan. Cline finished in **57 s** with a richer artifact
(real runbook, deeper tests, mock-aware rollback) but hallucinated the
opencode.json schema; OpenCode needed **2 supervised nudges / ~78 min
wall** (premature model stops + hung calls on the same `bench` model)
and produced a thinner artifact with a correct opencode schema but a
polluting rollback.sh. Both share model-level infra bugs (wrong
health endpoint, localhost api_base, fixed mock ports) that the mock
path cannot catch — neither stack would deploy correctly as-is.
No unattended routing enabled; S2 gate untouched.

Full analysis: `reports/comparison.md` · per-arm evidence:
`results/<arm>/{verifier,safety,rollback-evidence}.json|txt`,
`artifact.bundle`, `events*.jsonl`, `run.json`.
