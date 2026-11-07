# DevNest shadow-eval mode — runbook

Shadow mode runs **frozen identical fixtures** through independent
executor arms (deterministic L0 script, OpenCode, Devin) in **isolated
git worktrees**, verifies the artifacts with **held-out verifiers**, and
emits a benchmark report. It also carries the **rainy-day fallback
ladder** for routing work when the network degrades.

Everything lives in-repo:

- harness: `scripts/devnest/shadow_eval.py`
- fixtures: `evals/shadow/fixtures/<id>/`
- reports: `evals/shadow/reports/` (committed)
- runs + staged cache: `evals/shadow/runs|staged/` (gitignored, per-host)
- tests: `tests/devnest/test_shadow_eval.py`

## Everyday commands

```bash
H=scripts/devnest/shadow_eval.py
python3 $H probe                 # connectivity/tool/model snapshot
python3 $H matrix                # rung x PASS/DEGRADED/BLOCKED
python3 $H route "some task"     # which rung would take it
python3 $H route --fixture host-health
python3 $H run --fixture all --arm l0 --parallel 5
python3 $H run --fixture host-health --arm opencode \
    --model litellm/gemini-3.5-flash-lite
python3 $H run --fixture host-health --arm devin --allow-devin
python3 $H report                # benchmark md+json in evals/shadow/reports
python3 $H simulate --offline offline   # tailnet+WAN down, loopback ok
python3 $H simulate --offline airgap    # nothing reachable
python3 $H prestage              # stage model list + fixture manifest
python3 $H clean --run-id <id>   # drop worktrees+branches, keep artifacts
```

## Rainy-day ladder

| rung | executor | needs |
|---|---|---|
| L0 | deterministic fixture script | python3+git only |
| L1 | opencode → local ollama | loopback daemon + prompt ≤ 4000c |
| L2 | opencode → LiteLLM tailnet | idc03:4000 + key |
| L3 | opencode → Zen/remote | WAN |
| L4 | devin cloud | WAN + api.devin.ai |
| MANUAL | Tony | always |

Routing = cheapest rung that can pass given the live probe; a failed
rung escalates (`--failed L0,L1`). Offline rungs never load secrets —
`load_arm_env()` hard-refuses under `SHADOW_OFFLINE=1`.

## Invariants (don't break these)

1. Each arm gets its own worktree + `shadow/<run>-<arm>-<fixture>`
   branch; collision = hard refusal.
2. Arm worktrees sparse-exclude `evals/` — verifiers are truly held out.
   Arms writing outside `evals/shadow/task/` get flagged
   (`scope_violations`); mutating commands and verifier peeks are audited
   from the event log.
3. Shadow branches **never merge**. No auto-close, no push.
4. Fixtures are frozen: `inputs/` + `prompt.md` are copied verbatim to
   both arms; never edit a fixture mid-benchmark — bump the fixture id.
5. L0 legs must stay zero-secret, zero-network.

## Nested-Devin notes (measured 2026-10-27)

`devin -p` inside a shadow worktree needs
`--respect-workspace-trust false`; `--permission-mode smart` covers
read+write fixtures but declines `git` plumbing tasks — those need
`SHADOW_DEVIN_PERMISSIONS=dangerous`. `devin -p` emits no token JSON —
token metrics for the devin arm are null until a usage adapter exists.

## Extending

New fixture = `evals/shadow/fixtures/<id>/{task.yaml,prompt.md,l0.py,
verify.py,inputs/}`. `verify.py` must expose
`verify(task_dir) -> {verdict, checks}` and re-measure reality itself —
never trust the artifact's self-report. `l0.py` must produce the artifact
with no LLM and no network.
