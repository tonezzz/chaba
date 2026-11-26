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

### Managed Agents

`client.agents` / `agent=...` with a sandboxed filesystem, code execution, web
search, and triggers. Also `v1beta`-only. Worth a scoped eval against our
current hand-built agent loops, but it must not be conflated with the
Interactions API: one is a stateful conversation primitive, the other is a
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

`ThinkingConfig(thinking_level="high"|"medium")` is available on 3.8 Flash;
`minimal` is rejected on 3.8 Flash. Use `high` for hard maths/coding and
`medium` as the balanced default. This is distinct from the separate
`gemini-3.8-live-extended-thinking` Live model.

### Other levers already supported but under-used

- **Structured output** via `responseMimeType` + JSON schema, and strict
  function calling / mode compliance, for deterministic agent handoffs.
- **Explicit context caching** (`createCachedContent`) and **batch
  generation** for large, repeated corpora — both present on 3.8 Flash and
  the Gemini 4 line.
- **TTS / voice design / voice replication** via the 3.8 Flash TTS models —
  a separate path from Live audio, useful for pre-generated narration.
- **Computer use**, where a `safety_decision` of `require_confirmation`
  must be surfaced to the user and acknowledged with
  `safety_acknowledgement` before the action result.

## 3. Recommendations for this estate

1. Keep `gemini-3.8-live` pinned for `rview-live` and the default Live runtime.
2. Run the 20-fixture voice bench against
   `gemini-3.8-live-extended-thinking` **before** any pin change; it is
   `bidiGenerateContent`-only, so it needs the same harness shape.
3. For new text agents, evaluate Gemini 4 Carbon/Neon against current 3.x
   defaults and add the Interactions API for state.
4. Trial `gemini-decision-1` as a cheap gate where today we ask a full model
   for a yes/no judgment.
5. Load the official `gemini-api-dev` skill for any Gemini API code work.
6. Guardrails unchanged: no key, billing, or gateway edits without explicit
   go-ahead; keep OpenRouter/Ollama as real failover; no secrets, key names,
   project IDs, or topology on published pages.

## Evidence and references

- Live `v1beta/models` catalog probe, 2026-11-26 (65 models, filtered above).
- Live `POST /v1beta/decisions` probe, 2026-11-26, result quoted above.
- Context7 Gemini API docs: Interactions API, thinking levels, caching/batch,
  computer-use acknowledgement.
- `google-gemini/gemini-skills` — README and
  `skills/gemini-api-dev/SKILL.md` (current-model list and skill evaluation).
- Board card ADA-1440 / `gemini-dev-capabilities-research-2026-11-26`.
- Related prior pages: `Education:LLM Providers/Gemini API`,
  `Education:Ada-Developer-Paid-Model-Candidates`,
  `Education:Ada-Dev-Gap-Model-Vs-Harness`.
