# Dispatch outcome — jack-llm-stack-agent-eval (OpenCode vs Cline)

**Result: COMPLETE. Verdict — Cline wins this bounded build.**

## What was done

Matched, gated eval of OpenCode vs Cline on an identical brief:
design/configure/test/document a disposable Jack LLM stack (Ollama +
LiteLLM-compatible routing + OpenCode provider config + health checks +
secret placeholders + resource limits + rollback + runbook). Both arms
ran against LiteLLM alias `bench` (ollama_chat/qwen2.5:32b on kk-mac via
tailnet — $0 local spend), each in a fresh git repo under
`evals/jack-llm-stack-agent-eval/arms/`, with per-arm isolated HOME so
session state never touched the arm repos.

- **S0 shadow/replay**: independent verifier `harness/verify_stack.py`
  proven discriminating — reference fixture PASS, bad fixture FAIL with
  17 findings (fake sk-/AKIA secrets, prod host refs).
- **S1 supervised**: one build per arm, devin-supervised. No unattended
  routing enabled; S2 evidence gate untouched (opencode-lane still S0).
- **Verification**: both arms PASS the independent verifier (0 failed
  checks), their own `verify.sh` (rc=0), idempotent rollback evidence,
  and safety scan (0 violations; placeholder-shaped warnings only).

## Headline numbers

| | OpenCode | Cline |
|---|---|---|
| Wall time | ~78 min (3 attempts, 2 nudges) | 57 s (one-shot) |
| Tokens | 170K in / 7.8K out / 12.7K reasoning | 270K in / 9.2K out |
| Cost | $0 | $0 actual (cline nominal $0.665) |
| Human minutes | ~8 | ~1 |
| Artifact quality | correct opencode.json schema; thin runbook/tests; rollback.sh pollutes tree | richer runbook/tests/rollback; hallucinated opencode.json schema |

Both arms share model-level infra bugs the mock deployment cannot catch
(`/health/liveness` vs real `/health/liveliness`, `localhost` api_base
inside container, fixed mock ports 11434/4000, literal placeholder
apiKeys) — neither stack would deploy correctly on a real container
host as-is. Follow-up recommended: config-lint leg or live-litellm
smoke in a round 2.

## Where the deliverables are

- Comparison report: `evals/jack-llm-stack-agent-eval/reports/comparison.md`
- Evidence per arm: `evals/jack-llm-stack-agent-eval/results/<arm>/`
  (verifier.json, safety.json, rollback-evidence.txt, artifact.bundle,
  events*.jsonl, run.json, file-manifest.txt)
- Harness/brief/fixtures: `evals/jack-llm-stack-agent-eval/{brief,harness,fixtures}/`
- SSOT job doc: `docs/ssot/jobs/devnest/2026-11-24-jack-llm-stack-agent-eval.yml`
- Committed on branch `dispatch/20261124-170743-compare-opencode-and-cline-on-`
  as `2d931a2e9f` (not pushed, per dispatch rules).

## How to verify

```
cd evals/jack-llm-stack-agent-eval
python3 harness/verify_stack.py arms/opencode   # needs arm repo restored
python3 harness/verify_stack.py arms/cline
# or inspect committed evidence:
cat results/opencode/verifier.json results/cline/verifier.json
cat reports/comparison.md
```

Arm repos are gitignored at eval level; snapshots are in
`results/<arm>/artifact.bundle` (`git clone artifact.bundle` to restore).

lessons:
- opencode `run` buffers stdout — monitor via `--format json` events file + process table, not the log stream; premature `finish_reason=stop` from the model looks like a clean exit, so gate on "did it commit the artifact" not exit code.
- Per-arm isolated HOME must live OUTSIDE the arm repo (`arms/.<arm>.home`) — an early stray `.opencode.home` inside the eval dir nearly got committed as session state.
- Mock-deployment evals have a verification blind spot: both agents "passed" stacks with wrong LiteLLM endpoint names and localhost api_base — add a config-lint leg or live smoke before trusting mock-verified infra artifacts.
- `cline` CLI headless works: `cline auth -p openai-native -k $KEY -m bench -b $BASE --data-dir $DIR` then `cline --json --data-dir $DIR -c $DIR "$PROMPT"` — one-shot yolo completed a 12-file build in 57s.
- SSOT job YAML: bare continuation lines under a map need a key — an orphan scalar line fails pre-commit SSOT validation.
