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

`ollama serve` runs on kk-mac under the `adanest` account. Since
2026-11-19 the plist binds `0.0.0.0` — reachable directly on the tailnet
at `100.108.217.17:11434` (LAN `192.168.0.101:11434` + `192.168.2.90:11434`
too — verified answering 2026-11-24; bind durability confirmed in the
LaunchDaemon plist, narrow-to-tailnet still pending KK sudo — card
`kkmac-ollama-durable-bind`). Fleet traffic goes through idc03
`kkmac-admission-shim.service` (`127.0.0.1:11447`, fail-fast Ada Nest
gate); LiteLLM routes `ollama-*-kkmac` point at the shim. The old
`ssh -L 11445` tunnel (`kkmac-ollama-tunnel.service`) is a declared but
disabled fallback — it flapped ~19k restarts against a sleeping member
device and nothing consumes :11445 anymore.

## Verifier weakness found (OPS-1014, resolved 2026-11-24)

The `doc-draft` verifier passed a doc that ignored the task brief
(wrote a code-summary of runner-agent.py instead of model notes).
Two compounding causes: the card declared **no** verify contract at
all — `action.verify_contains`/`verify_sections` were never in
board-api's `ACTION_KEYS`, so the write door silently dropped them —
and even declared sentinels are mechanical, not semantic.

Resolution (card `doc-draft-verifier-semantic-gap`): the verifier now
supports optional `action.verify_regex` (patterns that must match) and
`action.verify_min_terms` (`{terms, at_least}` keyword coverage), and
all four `verify_*` keys are settable through board-api with shape
validation. The contract is held-out — the values are not injected
into the agent prompt, so the spec prose must still say what to write;
verify_* only enforces it. Declare strings/terms only a correct
deliverable contains — but the gate stays mechanical, so **doc quality
still needs human review at card closeout**.
