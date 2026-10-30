# docs/kb/opencode-lane-model-notes.md

Which LiteLLM models work on the OpenCode dispatch lane (idc02), what
each failure mode looked like, and how the lane contract constrains
model choice. Written from pilot evidence 2026-10-30.

## The contract models must satisfy

- `ops-readonly` emits **JSON** artifacts (`artifact.format: json`);
  `doc-draft` emits **markdown** (`artifact.format: md`). Both are
  message-mode: the agent's final message *is* the artifact.
- The runner writes files, not the agent. Agents must **emit** the
  artifact as their final message — every write/bash attempt in a
  read-only profile is denied, recorded in `events.jsonl`, and fails
  the job at closeout.
- The held-out verifier re-checks artifact content against reality
  (fresh host facts) plus sentinels from `action.verify_contains`.
  Denials or mutating commands fail closeout even if content is right.
- `RAILS_OPENCODE` in `scripts/board/runner-agent.py` is the prompt
  block for this lane: no board-api calls, no network; emit only the
  artifact. (The devin-executor rails previously caused a spurious
  denial by instructing a curl progress-post the sandbox denies.)

## Verified working

| Model | Route | Evidence |
|---|---|---|
| gemini-3.5-flash | `litellm/or-gemini-3.5-flash` | Full pass — health JSON artifact verified + merged (OPS-0998, merge `562d54fdd`) |
| qwen2.5:32b (kk-mac ollama) | `litellm/ollama-qwen32b-kkmac` | Full pass — doc-draft markdown verified + merged (OPS-1014). Content off-spec on first run (see below). ~6 tok/s |
| qwen3:8b (kk-mac ollama) | `litellm/ollama-qwen38b-kkmac` | Full pass — on-spec grounded KB doc merged (OPS-1024, merge `c1813b5a0`). ~4x faster than 32b, better instruction-following. **doc-draft default** |

## Failed / limited

| Model | Failure |
|---|---|
| `or-free-nemotron-nano` | Agentic loop can't emit-vs-write: 60/77 bash denials looping on `echo '{...}'`, never emitted. Honest fail. |
| `or-free-gemma31b` | Upstream `API_KEY_INVALID` at OpenRouter — not our key |
| `or-gemini-3.5-flash-lite` | Empties mid-agentic-loop (dies ~turn 5 with 0 output tokens) — unlike the AI-Studio-direct route |
| `litellm/gemini-3.5-flash-lite` | Proven model, but the upstream AI Studio project hits its monthly cap |

## kk-mac free lane

`ollama serve` runs on kk-mac under the `adanest` account, bound to
loopback only. Reachable via `ssh -L 11445:127.0.0.1:11434
kkkakk@kk-mac` on idc03; registered in LiteLLM as
`ollama-qwen32b-kkmac`. The tunnel is currently a nohup process —
needs a declared unit or a real `OLLAMA_HOST` bind on adanest's plist
before it is durable.

## Verifier weakness found

The `doc-draft` verifier passed a doc that contained the sentinel
strings but ignored the task brief (wrote a code-summary instead of
model notes). Sentinel checks are mechanical, not semantic — doc
quality still needs human review at card closeout.
