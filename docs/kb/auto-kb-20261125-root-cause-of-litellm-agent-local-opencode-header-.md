---
category: troubleshooting
status: verified
created: 2026-11-25
source: auto-kb
---

# Root cause of `litellm/agent-local` opencode header timeouts

## What it is

- Root cause of `litellm/agent-local` opencode header timeouts (OPS-1363, verified 2026-11-25): opencode auto-injects `<repo>/AGENTS.md` into every system prompt

## Context/Background

Created 2026-11-25 from automated KB creation workflow.

Additional context: session: litellm budget + agent-local opencode latency diagnosis 2026-11-25

## Key Details

### Technical Details
- **Generated**: 2026-11-25
- **Source**: Automated KB creation skill
- **Category**: troubleshooting

### Implementation
- Root cause of `litellm/agent-local` opencode header timeouts (OPS-1363, verified 2026-11-25): opencode auto-injects `<repo>/AGENTS.md` into every system prompt. In chaba that file is 81,199 bytes, inflating the real agent request to 117,919 bytes / ~35k input tokens. The kk-mac primary leg (`ollama_chat/qwen2.5:32b` @ :11447) was thermally denied (`temp_high`) and burned its 120s LiteLLM timeout before fallthrough; qwen2.5:7b @ tonydell then took 265.6s to first byte on that payload, past opencode's 300s `headerTimeout` and the lane's 420s wall clock.
- Verified measurements: real 118KB payload via agent-local = 265.6s first byte (qwen7b), 150s+ (llama3.2), 503 (kk-mac legs), 2.05s (gemini-3.5-flash-lite-free), 1.41s (gemini-3.5-flash-lite paid). Running opencode from a cwd with no AGENTS.md cut system prompt 103,723 -> 17,383 chars; qwen7b first byte 265.6s -> 64.1s. Lowering only the agent-local primary timeout 120s -> 15s cut a realistic 5k-char prompt 298s -> 15s.
- Fix pattern: (1) fast-fail thermally-throttled primary (`timeout: 15` on agent-local in `/home/tony/.config/litellm/config.yaml`); (2) run agent-local profile jobs from a scratch cwd OUTSIDE the repo with symlinks to `scripts/` and `evals/` — an in-repo scratch cwd still inherits AGENTS.md by ancestor walk; (3) put a $0 free leg (`gemini-3.5-flash-lite-free`) first in the agent-local fallback chain, keep local Ollama legs behind it and paid Gemini last.
- LiteLLM custom logger callbacks (`litellm_settings.callbacks` with `custom_callbacks.*`) load the module but `async_pre_call_hook` did not fire on proxy requests in the deployed LiteLLM 1.105.0 — do not rely on pre-call prompt trimming there without verifying dispatch.
- Gate status after fixes: timeout eliminated. An intermediate run landed a valid artifact with 13/14 checks at $0.0 cost; only `rank order holds` failed because the agent emitted results in tool order. Final fix: `evals/opencode-lane/profiles/info-find/profile.yml` rails now require the `results` array to be physically sorted mddb > web > github > ssot/health > mcp > code. FINAL S1 GATE PASS: `evals/opencode-lane/runs/p1-info-find-agent-local-test-20261125-184706`, 16/16 verifier checks, artifact landed, exit 0, wall 80.9s, $0.00 provider cost, no denials/mutations/scope violations. Local-only legs produced no tool calls/artifact — capability limit, not latency.

## Related Documentation

- **[auto-chaba-creation.md](../../.windsurf/workflows/auto-chaba-creation.md)** - Automated KB creation workflow

## Tags

- **auto-generated**: Automatically created KB entry
- **2026**: Year tag
