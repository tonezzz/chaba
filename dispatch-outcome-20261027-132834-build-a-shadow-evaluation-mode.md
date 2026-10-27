# Dispatch outcome — DevNest shadow-eval mode + rainy-day ladder

Card: devnest-rainy-day-parallel-eval. Runner: tony-macbook.
Branch: dispatch/20261027-132834-build-a-shadow-evaluation-mode (commit 0c7e3c1b3).

## What was built

- **`scripts/devnest/shadow_eval.py`** — the shadow harness:
  `probe` (connectivity/tool/model detection), `route` + `matrix`
  (rainy-day ladder L0→L4→MANUAL with PASS/DEGRADED/BLOCKED), `simulate`
  (offline/airgap routing proof), `prestage` (model+fixture manifest for
  offline use), `run` (isolated-worktree arm executor), `verify`
  (held-out verifier), `report` (benchmark md+json), `clean` (extract
  artifacts, drop worktrees+branches).
- **5 frozen paired fixtures** under `evals/shadow/fixtures/` —
  host-health, storage-dryrun, mcp-safety, worktree-safety,
  backup-freshness. Each ships `task.yaml` contract, `prompt.md`,
  deterministic `l0.py`, held-out `verify.py`, and frozen `inputs/`.
- **Isolation**: per-arm `git worktree add -b shadow/<run>-<arm>-<fix>`;
  collision = hard refusal; sparse-checkout excludes `evals/` so
  verifiers are absent from the arm's tree (true held-out); event logs
  audited for verifier peeks, mutating commands, and write-scope
  violations; `shadow/*` branches never merge.
- **Ladder**: L0 deterministic scripts → L1 local opencode+ollama
  (loopback, ≤4000c prompts) → L2 tailnet LiteLLM → L3 WAN
  LiteLLM/Zen → L4 Devin cloud → MANUAL gate. Cheapest-sufficient entry;
  failed rungs escalate via `--failed`. Secrets loader hard-refuses
  under `SHADOW_OFFLINE=1`.
- **Tests**: `tests/devnest/test_shadow_eval.py` — 20 tests covering
  fallback selection across connectivity states, capability matrix,
  secrets guard, fixture integrity. All green.

## Measured results (real runs, this host)

| arm | verdicts | wall | tokens |
|---|---|---|---|
| l0 | **5/5 pass** | ~6s | 0 |
| opencode (litellm/gemini-3.5-flash-lite) | **2/5 pass** | 27–83s | 35k–328k (heavy cache_read) |
| devin (nested `devin -p`) | **5/5 pass** | 27–60s | n/a (print mode emits none) |

Findings that are real eval signal, not harness noise:

- flash-lite early-stops: no artifact on mcp-safety + worktree-safety;
  `used_pct` emitted as float on storage-dryrun.
- Nested devin needs `--respect-workspace-trust false` +
  `--permission-mode smart` (git-plumbing tasks needed `dangerous` —
  `SHADOW_DEVIN_PERMISSIONS` env override added).
- Capability matrix on tony-macbook: L0 PASS, **L1 BLOCKED** (no local
  ollama), L2/L3/L4 PASS, MANUAL PASS.
- Offline + airgap simulations PASS: all 5 fixtures route L0,
  LLM-needing tasks fall to MANUAL, zero violations (no rung needing
  network/secrets selected).
- Zero mutations across all 19 arm runs: mutating_commands=[],
  scope_violations=[], deletions=[].
- Worktree-collision refusal verified live (re-run on existing run dir
  refused).

## Verify

- `python3 -m unittest discover -s tests/devnest` → 20/20
- `python3 scripts/devnest/shadow_eval.py matrix` → live capability matrix
- `evals/shadow/reports/2026-10-27-shadow-benchmark.md` — full run table
- `evals/shadow/reports/2026-10-27-offline-simulation-{offline,airgap}.md`
- run records/artifacts preserved under gitignored `evals/shadow/runs/`
  (this host); runbook: `docs/kb/devnest-shadow-eval.md`; job doc:
  `docs/ssot/jobs/devnest/2026-10-27-shadow-eval-mode.yml`

## Still impossible without network/Devin

- L2+ rungs (tailnet LiteLLM, Zen remote, Devin cloud) — airgap routes
  them to MANUAL.
- L1 needs a pre-pulled local ollama daemon — absent on macbook.
- Anything `needs_llm=true` under airgap → MANUAL by design.
- A *true* paired Devin arm = a real devin-dispatch session, not a
  nested `devin -p` (nested is DEGRADED: no token telemetry, permission
  quirks). Follow-up: pair = twin dispatch on the same fixture.
