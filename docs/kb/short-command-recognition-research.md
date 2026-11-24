# Short command recognition — research program

Status: active, 2026-10-27. Anchor card:
`docs/ssot/kanban/cards/devin-research-short-command-recognition-d948ed.yml`
(DEV-0484). Placement per Tony's card answer 2026-10-26: **chaba repo,
research + prototype under `docs/`, host-agnostic.** Companion prototype:
`docs/prototypes/short-command/` (stdlib-only, runs anywhere).

## Idea

A large share of turns aimed at Ada/Chaba are **short commands**: a few
words, one intent, zero or a handful of slots — *"turn off the kitchen
light"*, *"กี่โมงแล้ว"*, *"explain 0905"*, *"approve OPS-0912"*,
*"แก้ไขด้วย"*. Today most of these still ride the full pipeline:
STT → provider LLM turn → tool call → TTS. That costs provider quota,
exposes rate-limit latches, and adds seconds of latency to a 5-word ask.

A **short command recognizer (SCR)** is a coarse-to-fine gate that sits
in front of the provider turn and resolves cheap commands locally:

```
transcript ─► T0 grammar match ─► T1 exemplar similarity ─► T2 local router LLM
                │hit                  │hit                    │hit
                ▼                     ▼                       ▼
             intent+slots          intent+slots            intent+slots
                └────── miss on all tiers ──► normal provider turn
```

This is the same adaptive-depth pattern already proven twice in this
ecosystem: the tg_relay trivial-gate (card `ada-nest-trivial-gate`,
done 2026-10-22) and the cheap-agent cascade design
(`docs/kb/cheap-agent-cascade.md` — *"entered at the predicted cheapest
passing level, escalated only on gate failure, provided every lane has a
cheap honest verifier"*). SCR is that pattern specialized to the
command-shaped head of the turn distribution.

## What already exists in-system

| piece | where | what it does | gap |
|---|---|---|---|
| `command_lane` | ada-pi `backend/command_lane.py` (ADA-0364, done 2026-10-10) | routes short turns through a local `/v1/systemone` call for route+entity pick; deterministic time/direction; all actuation via tool_runner gates | one LLM call per command, 27–45 s/call measured on the 4b endpoint — needs a ~1b lane; no cheaper tier in front of it |
| trivial-gate | tg_relay cascade (done 2026-10-22, ada-voice `docs/ssot/jobs/ada/2026-10-22-trivial-gate.yml`) | tiny local specialist answers greetings/time/date/acks before an Ada turn | answers *queries*, doesn't extract/act on commands |
| devnest-tg-command-router | `scripts/devnest/devnest-tg-relay.py` on idc03 (job `docs/ssot/jobs/devnest/2026-10-26-tg-command-router.yml`) | anchored whole-message board commands (`explain <ref>`, `APPROVE <ref>`) via regex normalize + board-api | text-only, board-scope only — but proves the anchored-grammar pattern works against real traffic |
| local STT lane | qwen3-asr-0.6b-q8 on audio.cpp (job `docs/ssot/jobs/voice/2026-10-23-local-stt-lane-eval.yml`) | mean CER 0.212 over 28-clip real TG corpus (EN/TH/code-switch), RTF ~0.65 | feeds transcripts *to* SCR — SCR consumes its output, errors included |
| correction-command directive | job `docs/ssot/jobs/ada/2026-10-16-correction-command-directive.yml` (OPS-0567) | explicit correction commands ("แก้ไขด้วย", "remember this") authorize immediate memory writes | a command class SCR should recognize and route, not leave to persona prompt luck |

The shape of the gap: **three implementations of "recognize a short
command" exist already, each narrow** (regex for board commands,
systemone for voice commands, a specialist for trivial queries). The
research goal is the unified, tiered recognizer they are all instances
of — one grammar/similarity surface, one escalation contract, one
metrics definition, embeddable in each relay.

## Design space (external survey)

Ordered cheapest → most expensive per decision.

### T0 — template/grammar matching

- **hassil** (Home Assistant Assist): YAML sentence templates with
  alternation `(turn|switch)`, optionals `[the]`, and slots `{area}`;
  compiled to a matcher that returns intent + slot values. The
  `home-assistant-intents` package ships community-maintained templates
  for ~50 intents across dozens of languages, Thai included (`th`
  coverage is partial). Zero inference cost, deterministic, auditable.
- **regex/intent grammars**: Rhasspy's ini sentences, Mycroft Adapt,
  Dialogflow-style matched phrases — all the same idea. devnest's
  `explain|status <ref>` is a hand-rolled instance.

Strengths: microseconds, exact slots, no model, no GPU, fully testable
(sample every template). Weaknesses: only matches what you wrote;
brittle to ASR errors (one wrong word kills the match) and free
phrasings. This is why it must be a *tier*, not the whole system.

### T1 — exemplar / similarity matching

Represent each intent with 5–20 exemplar utterances; score the incoming
transcript against exemplars; accept above a threshold.

- **Lexical**: char-ngram/token-overlap similarity — stdlib, multilingual
  by accident (works on Thai script), robust to single-token ASR noise.
- **Embedding**: text-embedding model (local bge/gte-small, or an
  in-house lane), cosine over exemplar bank. Handles paraphrase the
  grammar missed; ~10–50 ms on CPU for short texts; needs an embedding
  lane per host or a shared endpoint.
- **Intent classifiers**: fine-tuned small encoder (SetFit-style,
  few-shot). Higher accuracy ceiling but a training loop to maintain —
  keep as an upgrade path, not v1.

### T2 — small local router LLM

A 0.6–4B instruct model asked to emit `{intent, slots}` JSON — exactly
what ada-pi's `command_lane` does via `/v1/systemone`. Generalizes
beyond written grammar; still local and free. Measured reality here:
27–45 s/call on the loaded 4b endpoint (OPS-0605 timeout storm is the
cautionary tale) — viable only on a 1b-class lane with a circuit
breaker, and only worth it after T0/T1 declined.

### Audio-side alternatives (no transcript needed)

- **KWS / wake-phrase**: openWakeWord (TFLite, server-side), microWakeWord
  (ESP32-S3/Android edge), sherpa-onnx KWS (3M-param transducer,
  open-vocabulary typed phrases), Picovoice Porcupine. These detect a
  *fixed phrase* in raw audio — the right tool for wake/attention and a
  small closed command set ("stop", "cancel"), not for slot-filling
  commands.
- **End-to-end SLU** (audio→intent direct): ESP-SR multinet (Espressif,
  on-chip command sets), SpeechBrain SLU, NVIDIA NeMo intent/slot
  models, Fluent-Speech-Commands-style training. Removes the ASR-error
  middleman but locks you to a trained intent set and English-centric
  tooling — poor fit for TH/EN code-switch.

### Comparison

| approach | per-call cost | latency | slots | TH/code-switch | ASR-noise tolerance | fit |
|---|---|---|---|---|---|---|
| T0 grammar (hassil-style) | ~0 | µs | exact | needs TH templates (writable) | poor | **tier 0, always first** |
| T1 exemplar (lexical) | ~0 | <1 ms | fuzzy | yes (script-agnostic) | moderate | **tier 1 default** |
| T1 exemplar (embedding) | tiny model | ~10–50 ms | fuzzy | model-dependent | good | tier 1 upgrade where a lane exists |
| T2 router LLM (~1b) | local GPU/CPU | ~1–5 s | free-form | model-dependent | good | tier 2, behind breaker |
| KWS (audio) | ~0 | real-time | none (fixed phrases) | needs trained phrase | n/a | parallel lane: wake + closed sets |
| e2e SLU (audio) | small model | real-time | trained slots | poor (EN-centric) | best | defer — retrain cost too high |
| provider turn | paid quota | seconds | free-form | best | best | **escalation, not default** |

## Recommended architecture

```
audio ─► [KWS lane: wake/closed-set, parallel]        text ─► normalize ─► SCR
            │                                                        │
            └────────────► STT (qwen3-asr local lane) ───────────────┘
                                                                    │
        T0 grammar (per-surface YAML: voice, tg, devnest, line) ─ hit?│
        T1 exemplar similarity (lexical now, embedding when lane) ─ hit?
        T2 router LLM (~1b, circuit-broken, optional) ─ hit?          │
                          │ miss everywhere                         │
                          ▼                                          ▼
                    normal provider turn              intent+slots ─► gate ─► act
```

Design rules carried from the cascade doc and the existing relays:

- **Every tier is gated by confidence, not order alone.** T0 hit =
  accept. T1 needs a score threshold with a gray band (accept / ask
  "did you mean X" / pass through). T2 needs schema-validated output.
- **Anchored forms only where mutation is possible.** devnest's rule —
  whole-message commands, never mid-sentence matching — generalizes: a
  recognizer that fires on *quoted* or *reported* speech is a bug.
  For voice, anchor on turn boundaries; for text, anchor on the whole
  message or an explicit prefix.
- **The verifier is separate from the matcher.** Intent extraction and
  authorization are different planes: `MemoryCorrect` may recognize
  perfectly and still require owner-identity before writing (the
  OPS-0567 rule — explicit correction *is* authorization, but only for
  memory-class commands; board mutations keep approver gates).
- **Shared grammar, per-surface binding.** One `commands` spec (intents,
  templates, slot lists) compiled per surface: voice turns get
  pronunciation-tolerant slot lists, TG gets anchored whole-message
  forms, DevNest keeps its approve-gate. The prototype demonstrates the
  shared spec; surfaces bind subsets.
- **Metrics from day one.** Per tier: fires, accepts, gray-banded,
  pass-through; plus deflection rate (provider turns avoided) and
  wrong-fire rate on a held-out corpus. Without this the gate is
  unverifiable — same lesson as `lane-metrics` for the bank router.
- **Thai is a first-class input.** Slot lists need Thai aliases
  (ห้องนั่งเล่น = living room), templates need Thai verb orders
  (เปิดไฟ…, ปิด…, กี่โมง), and code-switch ("เปิด the light") should
  degrade to T1 rather than fail hard at T0.

## Real-corpus calibration — 2026-11-24 (card scr-calibrate-t1-…-8ca63e)

Corpus built from the real TG voice refs used by the STT lane eval:
`eval/tg-voice-src/refs-all.jsonl` (28 clips, senders tony/tg-tony/
michael/corpus, 2026-10-10 → 2026-10-17) joined with
`results-qwen3-asr-q8.jsonl` (qwen3-asr-0.6b-q8 hyps — the production
STT output SCR would actually see). Two labeled corpora:

- `eval/corpus-tg-qwen.jsonl` — 28 items, `text` = qwen3 hyp
- `eval/corpus-tg-ref.jsonl` — same 28, `text` = Gemini reference
  transcript (upper bound on transcript quality)

**Labeling result: all 28 are `no_match`.** Every utterance is
conversational — status questions, transcript tests, voice-dub requests,
EN/TH/DE/TL/code-switch chat, 3 empty-STT clips. **Zero in-grammar
short commands exist in the real TG voice corpus.** That is itself the
headline: on today's TG voice traffic the recognizer's job is purely to
*not fire*; deflection ≈ 0% is correct behavior, and wrong-fire rate is
the only operative metric until command-shaped traffic shows up.
(8 newer manifest clips from 2026-10-25 → 2026-11-02 have no refs —
stt-lane assets predate them; corpus growth needs a re-run of
`gen_refs.py` + the qwen3 eval.)

### Score distributions (best T1 exemplar score, thresholds disabled)

| corpus | max non-command | min true-command (T1-resolved) |
|---|---|---|
| synthetic `corpus.jsonl` (51) | 0.216 ("tell me a story about a cat"→GetTime; "what is the capital of france"→GetDate 0.203) | 0.615 ("what day is it"→GetDate) |
| real TG qwen3 hyps (28) | **0.163** ("Yes, please run the web search…"→HassTurnOn) | n/a — no positives |
| real TG gemini refs (28) | 0.163 (same clip) | n/a |

Real-data shape: Thai items score ≤0.069; EN conversational items
cluster 0.08–0.16; the three empty-STT clips score 0.0. qwen3's
transliteration drift ("Claude"→"crowd", "Telegram"→"เทเลกาน",
"transcript"→"ทาร์สคริปต์") does not push scores *up* — noise lowers
similarity, it doesn't fabricate command likeness. T0 fired zero times
on real data (correct — nothing was a whole-message grammar match).

### Threshold recommendation

Wrong-fire requires `score ≥ accept`; the highest non-command score
ever observed across both corpora is **0.216**, the lowest true-command
T1 score is **0.615** — a safe gap of ~0.40. Recommended operating
point, mid-gap:

- **`accept = 0.40`** (was 0.55) — accepts every observed true command
  with ≥0.21 margin; wrong-fire margin ≥0.18 above the worst observed
  non-command.
- **`gray_lo = 0.25`** (was 0.45) — the [0.25, 0.40) band catches
  borderline near-misses for "did you mean X?" disambiguation. On the
  real corpus only 3/28 items even enter gray (top scores 0.163/0.158/
  0.150 at gray_lo≤0.15); at 0.25 nothing gray-bands — all pass
  through.

Measured wrong-fire rate on real data: **0/28 = 0%** at accept≥0.25
and at the recommended 0.40 (and 0/51 on synthetic ≥0.25; the 2
synthetic wrong-fires only appear at accept≤0.20). Deflection on real
TG voice: 0% — expected, there are no commands to deflect.

Caveats: n=28 with zero positives means **command recall on real
transcripts is unmeasured** — the accept threshold is bounded above by
the non-command ceiling (solid) but below only by synthetic positives.
Revisit when the corpus grows command-shaped clips (the 8 unref'd
manifest entries plus any future "turn on…" voice notes). If a "did
you mean" UX lands, gray_lo=0.25 is the band to wire it to.

### Which surface integrates first: **tg_relay**

- It already owns the cascade shape (trivial-gate) and consumes
  whole-message text — SCR's anchored-grammar rule maps 1:1, no voice
  turn-boundary problem.
- The measured risk it must control is exactly what we measured:
  wrong-fire on conversational Thai/EN/code-switch = 0% at the
  recommended thresholds.
- ada-pi `command_lane` has the bigger cost-reduction prize but sits
  on the live voice path with a 27–45 s/call T2 endpoint; SCR there
  should follow tg_relay's proven metrics, with T2 kept behind the
  circuit breaker. Integrate tg_relay first, port the same
  `commands.json` + thresholds second.

`eval/run_eval.py` gained `--corpus PATH` for alternate corpora;
`eval/corpus-tg-{qwen,ref}.jsonl` are the real-data sets, sources in
`eval/tg-voice-src/`.

## Prototype status

`docs/prototypes/short-command/` ships a working reference of T0+T1
(stdlib Python, no deps, host-agnostic) with T2 wired behind
`SCR_ROUTER_URL`. `commands.json` carries a starter grammar covering
the in-system command classes above: HassTurnOn/Off (EN+TH), GetTime/
GetDate, BoardExplain/Approve/Reject, MemoryCorrect (EN+TH), Greeting/
Thanks deflections. `eval/run_eval.py` scores corpora per tier — the 51-utterance synthetic
set plus the 28-clip real TG voice sets (qwen3 hyps + Gemini refs) added
2026-11-24; `--corpus PATH` selects alternates, `--sweep` scans T1
thresholds. See its README for usage.

## Research questions still open

1. ~~**Threshold calibration on real transcripts.**~~ **Resolved
   2026-11-24** — see "Real-corpus calibration" above: recommend
   accept=0.40 / gray_lo=0.25, wrong-fire 0/28 on real qwen3 output.
   Recall on real commands remains unmeasured (corpus has none).
2. **Grammar breadth vs wrong-fire rate.** How many templates can T0
   carry before near-misses beat the T1 threshold? HA ships ~50 intents
   for a reason — above that, intent collisions need slot-combination
   discipline.
3. **Which surface first.** tg_relay already has the cascade shape and
   a trivial-gate to measure against — cheapest integration. ada-pi
   command_lane has the highest cost-reduction value but a live voice
   path. Card it when the corpus calibration lands.
4. **KWS lane scoping.** Worth a separate probe: is there a closed set
   ("stop", "cancel", "ไม่ใช่") valuable enough to run sherpa-onnx KWS
   in parallel with STT, bypassing transcription entirely for those?
5. **T2 necessity.** If T0+T1 deflect ≥80% of short commands on the
   real corpus, T2 may never earn its keep — measure before standing up
   a 1b lane.

## Adjacent cardable work

- Calibrate T1 thresholds against the idc03 TG voice corpus (refs
  already exist — the STT eval assets).
- Extract devnest's command set into the shared `commands.json` grammar
  so the relay consumes the spec instead of inline regex.
- HA intent-template reuse probe: import the `home-assistant-intents`
  `en`+`th` sentence files as T0 grammar for the HA-control class —
  replaces hand-writing Hass* templates.
- KWS closed-set probe (question 4).

## References

- Internal: `docs/kb/cheap-agent-cascade.md`,
  `docs/ssot/jobs/devnest/2026-10-26-tg-command-router.yml`,
  `docs/ssot/jobs/voice/2026-10-23-local-stt-lane-eval.yml`,
  `docs/ssot/jobs/ada/2026-10-16-correction-command-directive.yml`,
  cards `ada-nest-trivial-gate`, `use-local-model-for-short-voice-commands-4916da`,
  `systemone-cmdlane-timeouts`.
- External: HA intent recognition + hassil
  (developers.home-assistant.io/docs/voice/intent-recognition),
  home-assistant/intents repo, openWakeWord, OHF micro-wake-word,
  k2-fsa/sherpa-onnx (KWS + ASR), ESP-SR, Picovoice Porcupine/Rhino.
