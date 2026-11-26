---
category: education
status: living — re-check the catalog before reusing any model ID
---

# Gemini developer capabilities beyond our current pins (2026-11-26)

Pointer-first record for the board card
`gemini-dev-capabilities-research-2026-11-26` (ADA-1440). Published to
`Education:Gemini-Developer-Capabilities-2026-11-26` through the board-api
`wiki-education` sink. **Research only — no key, billing, gateway, or model-pin
changes were made.**

## Why this exists

Our Gemini SSOT was updated for `gemini-3.8-live` voice work, but a live catalog
probe on 2026-11-26 shows the developer surface has moved well past the
3.8 Live pin. This page records what actually exists, what was verified, and
which gaps are worth evaluating before anyone changes a pin.

## 1. Catalog reality check (live `v1beta/models`, 65 models)

| Group | Model IDs observed | Methods |
|---|---|---|
| 3.8 text | `gemini-3.8-flash` | `generateContent`, `countTokens`, `createCachedContent`, `batchGenerateContent` |
| 3.8 speech | `gemini-3.8-flash-tts`, `gemini-3.8-flash-lite-tts` | `generateContent`, `countTokens`, `batchGenerateContent` |
| 3.8 live | `gemini-3.8-live`, `gemini-3.8-live-extended-thinking` | `bidiGenerateContent` only |
| Gemini 4 | `gemini-4-argon`, `gemini-4-carbon`, `gemini-4-hydrogen`, `gemini-4-neon` | `generateContent`, `countTokens`, `batchGenerateContent` |
| Omni | `gemini-omni-flash-preview`, `gemini-omni-1.1-flash`, `gemini-omni-1.2-flash` | `generateContent`, `countTokens` |
| Decisions | `gemini-decision-1` | `createDecision` only |

The takeaway: **3.8 is no longer just Live**. There is a 3.8 Flash text/TTS
line, a second Live variant with extended thinking, and a whole Gemini 4
generation. The voice pin stays as-is until the extended-thinking Live variant
is evaluated on the same fixture set.

## 2. Developer surfaces we are not using yet

### Interactions API (stateful agents)

`client.interactions.create(...)` with `previous_interaction_id` lets the
server hold conversation history instead of replaying it every turn. It is GA
on `v1` with SDK >= 3.0.0. For our agent loops this is the cleanest way to cut
prompt-token growth; it is not the same thing as the older
`generateContent`/`chats` history we currently send ourselves.

### Decisions API (`gemini-decision-1`)

A purpose-built, calibrated decision endpoint — `noul` (yes/no with
confidence), `choice`, and `score` rubrics — over text, images, video, audio,
and PDFs. It is `v1beta`-only via `client.decisions.create` (SDK >= 3.2.0) or
`POST /v1beta/decisions`, with 262k input tokens and **zero output tokens**.
Verified live on 2026-11-26 with a read-only probe:

```
input:  "The blue mug arrived cracked on Wednesday."
answer: {"is_damaged": {"confidence": 0.9703, "noul": 0.9703, "type": "noul"}}
usage:  96 input tokens, 0 output tokens
```

This is a strong fit for cheap, calibrated gates (triage yes/no, rubric
scoring) without generating a paragraph we then have to parse.

**Expanded eval (2026-11-26, 60 balanced briefs, zero output tokens):** after
Tony reviewed two more borderline labels, agreement at the default 0.5
threshold was **55/60 (0.9167)** — 25/30 READY approved and 30/30 NOT_READY
rejected, with **zero false approvals** (Brier 0.0842). A `p_yes >= 0.5162`
threshold calibrated on 40 briefs held up on 20 unseen briefs: 10/10 NOT_READY
rejected, 6/10 READY approved, zero false approvals. High-confidence reject
also replicated: 13/13 rejects at confidence ≥ 0.90 were genuinely NOT_READY.
This supports a **high-precision approve pre-filter**, not hands-off dispatch:
10 held-out negatives still leave roughly a 26% upper bound on the false-
approval rate at 95% confidence. See
`docs/ssot/jobs/devnest/2026-11-26-gemini-decision-1-approve-gate-expanded.yml`.

### Managed Agents

`client.agents` / `agent=...` with a sandboxed filesystem, code execution, web
search, and triggers. Also `v1beta`-only. **Verified on the free tier on
2026-11-26** with `agent=antigravity-preview-09-2026` and `environment="remote"`
(see receipt `docs/ssot/jobs/devnest/2026-11-26-gemini-managed-agents-eval.yml`):

| Task | Result |
|---|---|
| Fresh sandbox, Python write + read `/workspace/ada-proof.txt` | 31s, exact `ADA-MA-OK-42` in `code_execution_result` and `model_output`; 11,270 in / 111 out / 187 thought tokens, 3,441 cached |
| Reuse sandbox via `environment_id` + `previous_interaction_id` | 25s, same `environment_id`, file persisted and appended to `ADA-MA-OK-42-REUSED`; 11,979 in / 94 out / 119 thought tokens, 7,559 cached |
| Mount public GitHub repo at `/workspace/spoon-knife` and list files | completed in 288s only with `background: true` + GET polling; a synchronous call timed out at 290s |

Two cautions for our loops: raw REST `POST /interactions` has **no**
`output_text` field (that is SDK-only) — read `steps[].content` and
`steps[].result`; and a managed-agent call costs far more input tokens than a
plain model turn (11k–12k vs ~1.5k for the Decisions batch) even when the agent
only writes one short file. Cache hits rose from 3,441 to 7,559 on the reuse
turn, so sandbox reuse does reduce billable input. It must not be conflated with
the Interactions API: one is a stateful conversation primitive, the other is a
managed execution environment.

### Official `gemini-api-dev` skill

The `google-gemini/gemini-skills` repo publishes a skill that explicitly says
**its rules override training data** and lists current models (Gemini 4 Carbon
for hardest reasoning, Neon for fast end-to-end tasks, Hydrogen for balanced
agentic/multimodal work). Google's own evaluation reported correct API code
rising to 87% with Gemini 3 Flash and 96% with Gemini 3.1 Pro when the skill
is loaded. Practical rule: load it before writing or reviewing Gemini API
code, the same way we load `ansible-first` before host work.

### Thinking controls

On the Interactions API, thinking is configured with
`generation_config={"thinking_level": ..., "thinking_summaries": "auto"}`.
3.8 Flash supports `low|medium|high` (`minimal` is rejected); the lite models
default to `minimal` and also accept `low|medium|high`. Gemini 4 Neon and
Hydrogen add `xhigh`. Thought steps always carry a signature; the summary can
be empty, so code must handle that. This is distinct from the separate
`gemini-3.8-live-extended-thinking` Live model.

### Other levers already supported but under-used

- **Structured output**: legacy `generateContent` uses `responseMimeType` +
  JSON schema; the Interactions API uses
  `response_format={"type":"text","mime_type":"application/json","schema":...}`.
  Both streaming and non-streaming valid-JSON responses were verified on the
  free-tier lite model.
- **Context caching**: implicit caching is on by default for 2.5+ models, but
  explicit cache objects (`createCachedContent`) are **not** supported in the
  Interactions API or for Gemini 4 — only in `generateContent` on supported
  Gemini 3 / 2.5 models. Do not design a Gemini 4 agent around explicit caches.
  **Batch generation** remains a separate option for large repeated corpora.
- **TTS / voice design / voice replication** via the 3.8 Flash TTS models —
  a separate path from Live audio, useful for pre-generated narration.
- **Computer use**, where a `safety_decision` of `require_confirmation`
  must be surfaced to the user and acknowledged with
  `safety_acknowledgement` before the action result.

## 3. Recommendations for this estate

1. Keep `gemini-3.8-live` pinned for `rview-live` and the default Live runtime.
2. DONE: the 20-fixture voice bench on `gemini-3.8-live-extended-thinking`
   returned 20/20 ok but **zero tool calls** across tool-bearing fixtures. Do
   not promote it as the voice pin; `gemini-3.8-live` remains sole primary.
3. Gemini 4 Carbon/Neon remains untested — free tier returns 0 output tokens
   and the paid keys share a project at its monthly cap. Do not change the
   production agent path without a paid-tier repeat.
4. `gemini-decision-1` was evaluated: strong reject gate, then a 60-brief
   expansion gave 55/60 agreement with zero output tokens and zero false
   approvals. Use it as a high-precision approve pre-filter; keep human
   dispatch approval until a larger held-out set bounds the false-approval
   rate.
5. The official `gemini-api-dev` skill is installed and trialled (87.5% vs
   25% pass rate with vs without it); load it for any Gemini API code work.
6. Guardrails unchanged: no key, billing, or gateway edits without explicit
   go-ahead; keep OpenRouter/Ollama as real failover; no secrets, key names,
   project IDs, or topology on published pages.

## 4. Free-tier verification sweep (2026-11-26, follow-up)

All checks below used synthetic text/media and the existing free-tier key;
no key, billing, gateway, pin or production-path change was made. Full evidence
lives in `docs/ssot/jobs/devnest/2026-11-26-gemini4-interactions-text-agent-eval.yml`
and `scripts/voice-bench/results/g4-*20261126.json`.

### What works on `gemini-3.5-flash-lite`

| Surface | Observed |
|---|---|
| Stateful agent loop | 6/6 tool calls + 6/6 cross-turn recall on 6 four-turn tasks |
| Streaming text and streamed function calls | event sequence `created → steps → completed`; `arguments_delta` must be accumulated; resume via `previous_interaction_id` |
| Structured output | JSON Schema valid in both streaming and non-streaming modes |
| Background execution | `in_progress → completed` in ~8s, despite docs listing only Gemini 4/3.8 |
| Store/get/delete | full steps incl. thought signature retrievable, then deletable |
| Flex tier | `service_tier="flex"` accepted and echoed |
| Code execution | correct Fibonacci(20)=6765; 84 tool-use tokens, ~57s |
| Token counting | `countTokens` works even after generation quota is exhausted |
| Files API | upload / get / list / delete all work without generation quota; URIs are `/v1/files/<id>` |
| Managed Agents (`antigravity-preview-09-2026`) | fresh sandbox + code execution, sandbox reuse with file persistence, and GitHub repo mount all work on the free key (see section 2 and the managed-agents receipt); repo mount needs background mode |

### What does not

- **Priority tier** is accepted but silently reported as `standard` on free
  tier — always check the echoed `service_tier` before assuming Priority.
- **Implicit caching** produced zero hits even with a ~6,000-token shared
  prefix; flash-lite is absent from the documented cache-minimum table.
- **Google Search grounding** returned 429 on the free-tier key (documented as
  paid-tier only), so it is a quota boundary, not a capability result.
- **Batch `batchGenerateContent`** returned HTTP 400 `FAILED_PRECONDITION` on
  the free key for both `gemini-3.5-flash-lite` and `gemini-3.8-flash` with a
  one-request inline job. Documented as 50% of interactive price and with its
  own rate limits; treat free-tier access as unavailable until confirmed on
  paid capacity. This is an observed precondition, not a model capability
  failure.
- **Generation quota**: 500 requests/day per model. The final surfaces
  (thought summaries, inline-image generation, OpenAI compatibility) all hit
  this cap with ~17h to reset. They are **unverified**, not failed.
- **Image token estimate**: docs say images ≤384px count as 258 tokens, but
  `countTokens` reported **1,089 image tokens** for a 64×64 PNG on flash-lite.
  Measure with `countTokens`; do not budget from the table.

### `gemini-3.1-flash-lite` vs `gemini-3.5-flash-lite`

Four identical stateful tasks gave both models 4/4 relaxed tool calls and 4/4
recall with ~3.9k input / ~0.5k output tokens. 3.1 scored 0/4 on strict topic
matching only because it enriches topic arguments with recalled context;
attendees, date and time were exact on 4/4. 3.1 single-call latency varied
136s / 2.9s / 69s versus 3–6s for 3.5 — free-tier throttling, not a model-speed
result. Keep 3.5 as the comparison baseline.

## Evidence and references

- Live `v1beta/models` catalog probe, 2026-11-26 (65 models, filtered above).
- Live `POST /v1beta/decisions` probe, 2026-11-26, result quoted above.
- Context7 Gemini API docs: Interactions API, thinking levels, caching/batch,
  computer-use acknowledgement.
- `google-gemini/gemini-skills` — README and
  `skills/gemini-api-dev/SKILL.md` (current-model list and skill evaluation).
- Board card ADA-1440 / `gemini-dev-capabilities-research-2026-11-26`.
- Free-tier follow-up: board card ADA-1451 /
  `gemini4-interactions-text-agent-eval-2026-11-26`; harnesses
  `scripts/voice-bench/g4-interactions-{eval,surfaces,advanced,model-compare,misc-nogen}.py`
  and JSONs under `scripts/voice-bench/results/`.
- Managed Agents: board card ADA-1440 /
  `docs/ssot/jobs/devnest/2026-11-26-gemini-managed-agents-eval.yml`;
  harnesses `scripts/voice-bench/g4-managed-agents-eval.py` and
  `g4-ma-repo-bg.py`, JSONs `g4-managed-agents-eval-20261126.json` and
  `g4-ma-repo-bg-20261126.json`.
- Related prior pages: `Education:LLM Providers/Gemini API`,
  `Education:Ada-Developer-Paid-Model-Candidates`,
  `Education:Ada-Dev-Gap-Model-Vs-Harness`.
