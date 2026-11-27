---
category: education
status: living — re-check the catalog before reusing any model ID
---

# Gemini developer capabilities beyond our current pins (2026-11-26)

Pointer-first record for the board card
`gemini-dev-capabilities-research-2026-11-26` (ADA-1440). Published to
`Education:Gemini-Developer-Capabilities-2026-11-26` through the board-api
`wiki-education` sink (revision 5, MediaWiki revid 809, 2026-11-27).
**Research only — no key, billing, gateway, or model-pin changes were made.**

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

**110-brief held-out comparison (2026-11-27):** a fresh, manually vetted
55 READY / 55 NOT_READY set, disjoint from the training and earlier holdout
sets, was judged by both arms with identical criteria.

| Arm | Approvals / 55 READY | False approvals / 55 | Accuracy | Brier | Output tokens | Latency |
|---|---|---|---|---|---|---|
| `gemini-decision-1`, old calibrated threshold 0.5162 | 37 | 1 (Wilson 95% 0.32–9.61%) | 82.73% | 0.1248 | 0 | 0.77s |
| `gemini-3.8-flash` boolean judgment | 42 | 0 (upper bound 6.53%) | 88.18% | 0.087 | 2,723 (+10,940 thought) | 252s |

Agreement was 98/110 (89.09%); the full model was right on 9 of 12
disagreements. Its 20,274 total tokens and ~5-minute latency make it a poor
fit for a per-card gate, but the Decisions API's single false approval means
the arms are still statistically compatible on precision — this does **not**
clear the gate for hands-off dispatch. Thresholds tuned on this holdout
(0.536574 for Decisions, 0.25 for the full model) are candidates only until
validated on a fresh negative set, and the confidence ≥ 0.90 auto-reject
shortcut regressed (one genuinely READY brief was confidently rejected).
Note that production has no LLM dispatch judge at all — it uses deterministic
`ada_preflight` gates plus human approval — so this is a full-model
generative stand-in, not a production path being replaced. Evidence:
`scripts/voice-bench/results/g4-decision-gate-heldout110-graded.json`.

**Production rule-gate baseline (2026-11-27):** replaying `ada_preflight`
against the same 110 card YAMLs showed there is no production LLM dispatch
judge to replace. `typed_dispatch_available` is hardcoded `False`, so
`ready_for_dispatch` is always False and the menu never offers *Approve
dispatch*. The gate is a workflow precondition check, not a semantic
readiness classifier: `no_open_requests` alone would approve 52/55 negatives
(precision 0.4526), `safe_scope` 51/55 (precision 0.2917), and both together
give precision 0.25 / recall 0.29. A model judgment would add 46 approvals
beyond the wired gate, 45 genuinely READY, but all 46 are blocked by
non-backlog column and missing typed dispatch envelope. Keep any model gate
**after** preflight and behind human approval, never as a bypass. This
comparison is a workflow-state baseline, not an apples-to-apples accuracy
test, because the holdout deliberately used real cards regardless of column.
Evidence: `scripts/voice-bench/results/g4-production-gate-baseline-20261127.json`.

**Independent validation (2026-11-27):** a fresh 130-brief set (60 READY /
70 NOT_READY), disjoint by card ID and normalized brief from the 60-brief
train set, the 41-brief probe, and the 110-brief holdout, tested the tuned
thresholds. The Decisions API reproduced high precision: at the default 0.5
threshold it approved 48/60 READY and 2/70 negatives (precision 0.96, Brier
0.0812), in 0.96s with 19,511 input tokens and **zero output tokens**. At the
holdout-tuned `p_yes >= 0.536574` it left one false approval, but that brief
(`gemini-dev-capabilities-research-2026-11-26`) had a spec and was dispatched —
a `not yet in our SSOT` marker misfire, not a model error. The other false
approval (`opencode-safe-storage-cleanup-report`) is the same kind of marker
misfire (`only after policy checks` is an in-task constraint). With those two
labels corrected, all three thresholds have zero false approvals and
`0.536574` gives 44/62 READY approved (recall 0.71). Primary metrics keep the
as-built labels; corrected numbers are a sensitivity read only.

The **confidence >= 0.90 auto-reject shortcut is dead**: 67 cases crossed the
threshold and four genuinely READY briefs were high-confidence-ready
(`p_yes` 0.92-0.93: `disk-guard-ssot-enforce`, `key-watch-monitor`,
`lesson-qc-sweep`, `mcp-kornia-omen-registration`). It fails under both raw
and corrected labels; do not adopt it. The negative pool is skewed — 65/70
are the "read the note / check the note" template family — so this validates
deferral-to-note negatives well but other negative types less. The full-model
arm was blocked (`gemini-3.8-flash` 503 on 3 attempts, alternates 503/429/404),
so its 0.25 threshold remains unvalidated. Evidence: receipt
`docs/ssot/jobs/devnest/2026-11-26-gemini-decision-1-approve-gate-expanded.yml`
and `scripts/voice-bench/results/g4-decision-gate-validation130-graded.json`.

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

**Task-matched cost comparison (2026-11-27):** the same Fibonacci(20) prompt
was run on the hand-built Interactions lite + `code_execution` arm and on the
Managed Agents remote sandbox. Both answered `6765`. The hand-built arm used
19 in / 66 out / 84 tool-use tokens (169 total) in 56.9s; Managed Agents used
11,189 in / 88 out / 168 thought tokens (11,445 total, 3,415 cached) in 31.1s.
That is ~68x total and ~589x input tokens for ~0.55x wall time on this one task
(n=1, model-class dependent). Use Managed Agents only for work that genuinely
needs a persistent sandbox. Evidence:
`scripts/voice-bench/results/g4-managed-agents-cost-comparison-20261127.json`.

**Web search and triggers (verified 2026-11-27):** the same managed agent
accepted `tools=[{"type":"google_search"},{"type":"url_context"}]` and answered
a factual lookup with `Asia/Bangkok` plus an IANA source URL in 45.6s. Steps
were `google_search_call -> google_search_result -> thought -> model_output ->
thought`: one grounding call, 16,794 total tokens (16,382 in, 8,146 cached,
55 out, 357 thought). This is a different path from `generateContent` Search
grounding, which still 429s on the free key. Triggers bind an agent, remote
environment, prompt and cron schedule into a persistent resource whose
environment is reused between runs; a create / get / delete probe on
`0 0 1 1 *` UTC returned `active`, next run `2027-01-01T00:00:00Z`, and an
empty list after deletion. Use stored credentials for unattended runs, not
inline tokens, and delete probe triggers.

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
   approvals. A 110-brief disjoint holdout bounded the false-approval rate at
   0.32–9.61% and placed a full-model stand-in ahead on accuracy (88.18% vs
   82.73%) but far behind on cost and latency. Keep it as a high-precision
   approve pre-filter with human dispatch approval. The independent 130-brief
   set confirmed the Decisions threshold has zero genuine false approvals
   (one raw-label "false approval" was a note-marker misfire), but the
   confidence >= 0.90 auto-reject shortcut is rejected and the full-model
   threshold is still unvalidated. Production has no model judge and preflight
   cannot approve at all today, so a model gate must sit after those
   preconditions, never bypass them.
5. The official `gemini-api-dev` skill is installed and trialled (87.5% vs
   25% pass rate with vs without it); load it for any Gemini API code work.
6. DONE: Managed Agents verified on the free tier and cost-compared on a
   task-matched Fibonacci(20) prompt (~68x total tokens, ~589x input tokens,
   ~half the wall time versus the hand-built lite loop). Use for real sandbox
   work only; do not promote into a runtime path.
7. Guardrails unchanged: no key, billing, or gateway edits without explicit
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
- **Google Search grounding on `generateContent`** returned 429 on the free-tier
  key (documented as paid-tier only), so it is a quota boundary, not a capability
  result. The Managed Agents `google_search` tool is a separate path and did
  work on the free key (see section 2).
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
- Managed Agents web search and triggers: live `POST /interactions` and
  `POST/GET/DELETE /v1beta/triggers` probes on 2026-11-27; one grounding call,
  16,794 total tokens; trigger created `active` with a far-future schedule and
  deleted in the same probe.
- 110-brief held-out comparison: receipt
  `docs/ssot/jobs/devnest/2026-11-26-gemini-decision-1-approve-gate-expanded.yml`
  plus harnesses `scripts/voice-bench/g4-decision-gate-heldout110-{build,grade}.py`
  and JSONs `g4-decision-gate-heldout110-*` under
  `scripts/voice-bench/results/`. No wiki publish of these results without a
  separate go-ahead.
- Production gate baseline: harness `scripts/voice-bench/g4-production-gate-baseline.py`
  and result `scripts/voice-bench/results/g4-production-gate-baseline-20261127.json`,
  replaying `ada_preflight` from `ada-voice/opencode/ada_mcp.py` against the
  same 110 cards.
- Independent validation: harnesses
  `scripts/voice-bench/g4-decision-gate-validation130-{build,grade}.py` and
  JSONs `g4-decision-gate-validation130-*` under
  `scripts/voice-bench/results/`, including the label-noise sensitivity read.
- Related prior pages: `Education:LLM Providers/Gemini API`,
  `Education:Ada-Developer-Paid-Model-Candidates`,
  `Education:Ada-Dev-Gap-Model-Vs-Harness`.
