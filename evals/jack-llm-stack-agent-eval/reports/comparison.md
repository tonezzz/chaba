# Jack LLM-stack agent eval — OpenCode vs Cline (matched benchmark)

Card: `jack-llm-stack-agent-eval` · Date: 2026-11-24 ·
Host: tony-macbook (no container runtime → mock deployment required) ·
Model (both arms): LiteLLM alias `bench` → `ollama_chat/qwen2.5:32b` on
kk-mac via tailnet — **$0 actual spend** (local upstream).

## Verdict

**Cline wins this bounded build** — one-shot completion in 57 s with a
verified, higher-quality artifact. OpenCode required 2 supervised nudges
and ~78 min wall to reach a verified-but-thinner artifact; its agent
loop repeatedly hit premature `finish_reason=stop` and hung calls on the
same model. Neither arm produced a stack that would actually deploy
correctly on a container host — both share model-level infra bugs the
mock path cannot catch. **No unattended routing enabled**: the existing
S2 evidence gate is untouched (lane remains S0).

## Matched conditions

| | OpenCode arm | Cline arm |
|---|---|---|
| CLI | opencode 1.19.4 `run --format json` | cline 3.0.75 `--json` one-shot yolo |
| Provider path | `OPENCODE_CONFIG=harness/opencode.eval.json` → litellm-eval | `openai-native` auth → litellm `:4000/v1` |
| Model | `bench` | `bench` (identical) |
| Brief | `brief/task-brief.md` verbatim | same file verbatim |
| Workspace | `arms/opencode` fresh git repo | `arms/cline` fresh git repo |
| Mode | auto-approve (eval config) | yolo default |
| Order | first (model cold-ish) | second (~4 min later, model warm) |

## Required evidence per arm

| Evidence | OpenCode | Cline |
|---|---|---|
| Committed artifact | PASS — commit `b483b52` (+init), clean tree | PASS — 3 commits, clean tree |
| Deterministic tests | PASS — arm `verify.sh` rc=0 (4.2 s under verifier) | PASS — rc=0 (2.2 s) |
| Independent verifier | PASS — `results/opencode/verifier.json`, 0 failed checks | PASS — `results/cline/verifier.json`, 0 failed |
| Safety ledger | PASS — 0 violations, 3 placeholder-warnings (`results/opencode/safety.json`) | PASS — 0 violations, 4 warnings |
| Wall time | **~78 min total** (attempt1 174 s + nudge1 ~50 min timeout + nudge2 ~25 min timeout; ~23 min active model time) | **57 s** |
| Token/cost | 170 K in / 7.8 K out / 12.7 K reasoning (459 K total incl. cache reads); $0 | 270 K in / 9.2 K out across 25 iterations; $0 actual (cline nominal $0.665) |
| Human minutes | ~8 (2 nudges + monitoring) | ~1 (monitoring only) |
| Retris | 2 supervisor nudges; 3 premature model stops; 1 hung call killed by timeout | 0 — single pass, `done` event |
| Rollback evidence | `rollback.sh` rc=0 ×2 idempotent — **but leaves `.bak` files + `__pycache__` (dirty tree) and never tears down mock servers** | `rollback.sh` rc=0 ×2 idempotent — tears down mock via `/tmp` PID files, restores `.bak`, tree stays clean |
| Artifact bundle | `results/opencode/artifact.bundle` | `results/cline/artifact.bundle` |

## Artifact quality (beyond the checklist floor)

The verifier is a floor; manual review of the committed trees:

**Cline — stronger:**
- `RUNBOOK.md`: real operator doc — ASCII architecture diagram, model
  rationale with memory math, copy-paste deploy/verify/rollback
  commands, failure-mode troubleshooting, model-change procedure.
- `tests/test_stack.py`: parses compose YAML structurally, asserts
  resource limits, asserts no real keys (90 lines vs OC's 38).
- `docker-compose.yml`: `ollama_data` named volume (model persistence),
  `${LITELLM_MASTER_KEY:-…}` env interpolation, `--num_workers 1`.
- `rollback.sh`: docker + mock-PID teardown + config restore; verified
  idempotent and non-polluting.
- **Defect:** `opencode.json` uses a **hallucinated schema** —
  `provider.{name,type,baseUrl,apiKey,model}` is not the real opencode
  provider format (`provider.<id>.{npm,options,models}`). Real opencode
  would not parse it correctly.

**OpenCode — correct core schema, thinner surround:**
- `opencode.json`: structurally valid opencode provider config
  (`npm`, `options.baseURL`, `models` map) — the one thing Cline got wrong.
- `RUNBOOK.md`: skeletal — section headers with 1–2 lines, no diagram,
  no commands beyond script names.
- `tests/test_stack.py`: existence + keyword checks only.
- `rollback.sh`: creates `.bak` files it never cleans (verified: run
  leaves `env.example.bak`, `opencode.json.bak`, `__pycache__` → dirty
  tree), no mock-server teardown.
- `docker-compose.yml`: no ollama model volume (models lost on
  `down -v`), literal placeholder env values.
- Self-corrected its own `verify.sh` rollback bug during nudge 3 —
  genuine iterate-and-fix behavior.

## Shared defects (both arms — model limitation, not harness)

Both agents independently produced stacks that pass their own mock
verify yet would fail on a real container host:

1. `/health/liveness` in compose healthchecks — LiteLLM's real endpoint
   is `/health/liveliness` (canonical misspelling). Mock implements
   whatever the agent chose, hiding the error.
2. `api_base: http://localhost:11434` inside litellm config — inside
   the litellm container `localhost` is the container itself; must be
   the compose service name (`http://ollama:11434`).
3. `ollama/` vs `ollama_chat/` LiteLLM provider prefix ambiguity for
   chat completions.
4. Mock servers hardcode ports 11434/4000 — collides with real
   Ollama/LiteLLM defaults (worked here only because host ports were
   free).
5. Literal `sk-placeholder-…` apiKey values instead of env references
   in `opencode.json` / compose env.

The mock-deployment requirement created a verification blind spot:
nothing exercises the real LiteLLM/opencode semantics. Recommend a
follow-up round adding a config-lint check (real endpoint names,
service-name api_base, volume presence) or a live-litellm smoke leg.

## Stage accounting

- **S0 shadow/replay**: verifier proven discriminating —
  `results/s0-reference-verifier.json` PASS,
  `results/s0-bad-verifier.json` FAIL (17 findings incl. fake secrets +
  prod refs).
- **S1 supervised**: one build per arm, devin-supervised, all evidence
  above recorded.
- **S2**: not entered — no unattended routing enabled; the opencode-lane
  graduation gates (5 independently verified jobs) still govern.

## Caveats

- Sequential arms on a shared local model: OpenCode ran first (model
  colder); Cline ran ~4 min later (likely warmer). Active model time
  differs ~25×, far beyond warm-up effects, but backend warmth is not
  client-visible — treat wall-time as directional, not precise.
- Cline's 57 s / 25-iteration run is verified real (events + committed
  files + verifier pass) but per-call upstream latency is not visible
  client-side; LiteLLM `/key/info` confirms only aggregate key spend.
- Both arms are single samples of one model (`qwen2.5:32b`); results
  measure *harness×model* fitness, not the tools in general.
