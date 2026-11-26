# Task: Disposable Jack LLM stack (bounded eval arm)

You are building a **disposable** LLM stack for "Jack" (a member's small
Apple-Silicon Mac used for local learning experiments). Everything you
produce lives in **this git repository only**. Commit your work before
you finish — the committed tree is the deliverable.

## Required stack contents

1. **Local Ollama model** — pick ONE small quantized coding-suitable
   model that fits Jack's M2 Mac with 8 GB unified memory (stay in the
   ~1.5B–4B range, Q4-class quant). Record the choice and why in the
   runbook.
2. **LiteLLM-compatible routing** — an OpenAI-compatible gateway config
   (LiteLLM `config.yaml` style) that exposes the local Ollama model
   under a stable alias, with health/routing settings appropriate for a
   single-node disposable deployment.
3. **OpenCode provider config** — an `opencode.json` (or `.jsonc`)
   snippet configuring a provider that points at the LiteLLM endpoint
   using an OpenAI-compatible API, with the model alias wired in.
4. **Health checks** — a script that verifies each layer
   (Ollama reachable + model present, LiteLLM liveliness + a real chat
   completion round-trip, OpenCode config parses and references the
   right endpoint/model).
5. **Secret placeholders** — `env.example` (or equivalent) with
   placeholder values ONLY. No real keys, tokens, or passwords anywhere
   in the repo — configs must reference env vars or `<PLACEHOLDER>`
   style values.
6. **Resource limits** — concrete limits for every service: memory,
   CPU, pids/parallelism, and Ollama-side caps (loaded models, keep-alive,
   context size). Express them in whatever deployment format you choose
   (compose, quadlets, or plain run scripts) AND make them visible to a
   reviewer reading the files.
7. **Rollback** — `rollback.sh` that returns the stack to its pre-deploy
   state: stops/removes services, restores any backed-up config, and is
   safe to run twice (idempotent).
8. **Operator runbook** — `RUNBOOK.md`: architecture diagram (ASCII ok),
   deploy steps, verify steps, rollback steps, failure modes, and how an
   operator changes the model.
9. **Tests** — deterministic, offline-capable tests (e.g. Python
   `unittest` or bash) that validate the artifacts: configs parse,
   required keys/limits/placeholders are present, scripts are
   executable, runbook covers required sections.
10. **Mock deployment** — the eval host has **no container runtime**.
    Provide a mock path (e.g. `mock/` stub servers or `--mock` modes)
    so `verify.sh` can exercise deploy → healthcheck → failure-injection
    → rollback end-to-end on localhost without docker/podman. The real
    deployment artifacts (compose/quadlets) must still be present and
    correct for an actual container host.

## Hard constraints

- No production DNS, Cloudflare, or public exposure — bind to
  localhost/tailnet-placeholder addresses only.
- No real Jack credentials, no Ada/Devin memory systems, no household
  Home Assistant, no external provider spend — Ollama + LiteLLM only.
- Do not modify anything outside this repository.
- `verify.sh` at repo root must run the full check suite and exit 0 on
  a clean checkout of your committed tree.
- Failure injection must be part of verify: e.g. stop the mock backend
  and confirm healthcheck fails clearly, then confirm rollback restores
  a clean state.

## Deliverable checklist (all required)

- [ ] stack definition files (compose and/or quadlets)
- [ ] LiteLLM routing config
- [ ] OpenCode provider config
- [ ] `healthcheck.sh` (or equivalent)
- [ ] `env.example` with placeholders only
- [ ] resource limits in deployment files
- [ ] `rollback.sh` (executable, idempotent)
- [ ] `RUNBOOK.md`
- [ ] tests + `verify.sh` (executable, exits 0)
- [ ] mock deployment path exercised by verify.sh
- [ ] everything committed to git
