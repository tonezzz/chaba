# Short command recognition — research program

Card: `devin-research-short-command-recognition-d948ed` (ref DEV-0484,
follow-up OPS-0919). Placement decided by Tony 2026-10-26: **chaba
repo, research + prototype under `docs/`, host-agnostic.**

Status: research + working prototype landed 2026-11-24 (attempt 2 —
attempt 1's artifacts were lost uncommitted; see job record).

---

## 1. Problem

Short commands — "status", "play", "turn off the AC", "explain
OPS-0912", "หยุดเพลง" — are the highest-frequency, most mechanical
inputs our voice/text lanes receive. Today every one of them costs a
full turn: STT -> LLM/provider -> TTS, or an Ada/provider text turn.
That is slow (seconds), expensive (provider tokens on every "status"),
and rate-limit exposed.

The question: **how cheap can command recognition get before it must
escalate — without ever acting on a guess?**

### What counts as a command

A short command is a bounded intent + optional slots (device, card
ref, volume delta, track) that maps to a *deterministic, already-built
handler*. It is NOT:

- an open question ("why did the deploy fail")
- a task request ("write me a poem", "ช่วยแปลประโยคนี้")
- chit-chat / acks ("ok", "good morning") — the trivial-gate's job
- a compound request needing planning ("turn it down and dim the lights")

The boundary is the whole game: **the recognizer's only sin is the
wrong-fire** — claiming a non-command, or the wrong intent, and acting
on it. A missed command just costs the provider turn it would have
cost anyway. Every design below is precision-first.

## 2. Design-space survey

Two insertion points exist: **pre-STT** (on the audio) and
**post-STT** (on the transcript). Our lanes are mostly post-STT — TG
voice notes already arrive as text via ada-stt, and TG/LINE text
messages skip audio entirely.

### Pre-STT (audio domain)

- **VAD -> wake-word/keyword-spotting cascade.** The industry shape:
  a tiny always-on detector gates everything downstream (Google's KWS
  cascade, arXiv:1712.03603; Reson8 wiki overview). openWakeWord runs
  ONNX on CPU at ~1.4ms/80ms block. Relevant only for always-listening
  surfaces (ha-live mic stream); TG lanes get audio after the fact.
- **ASR-free speech-to-intent.** Google's end-to-end model maps
  waveform segments straight to intent+slots, no transcript
  (arXiv:2011.04884, Fluent Speech Commands SOTA). Tiny footprint,
  streaming — but a *trained* model per intent set, and Thai data is
  the constraint.
- **Audio-embedding <-> text-embedding matching.** Encode the spoken
  clip and the known command phrases into one space; nearest neighbor
  IS the classification (ESP32-S3 writeup, ajv009.com). Elegant —
  skips STT entirely — but needs a cross-modal encoder we don't have.
- **Grammar-constrained ASR.** Vosk-style grammar restricts decoding
  to the command vocabulary (~0.1s, near-zero WER in-grammar — Voxa
  case study). Hybrid pattern: constrained model for commands, free
  Whisper for everything else, decided by... a classifier. Chicken-
  and-egg unless you run both or gate on duration.

Verdict for us: pre-STT pays off only on always-listening surfaces.
The ha-live bridge is the one candidate; TG lanes don't need it.

### Post-STT (text domain) — where this program lives

```
transcript/text
   |
   v
T0  deterministic: exact phrase table + anchored, operand-gated regex
   |   $0, ~microseconds, precision by construction on covered forms
   v  (miss)
T1  similarity: char n-gram TF-IDF (proto) or embedding NN
   |   vs per-intent prototypes; accept/gray/reject zones + margin gate
   v  (gray/reject)
T2  local small-LLM route+entity pick (command_lane -> /v1/systemone)
   |   ~seconds, $0, handles paraphrase + slots
   v  (no confidence / not a command)
T3  full pipeline: provider turn / Ada turn (today's behavior)
```

This is the same shape as every production cascade found in the
survey — and the same philosophy as our own cheap-agent-cascade
(OPS-0810): *entry-level prediction + gate-gated escalation*, where
each rung has a cheap honest verifier. Voxa's rule applies verbatim:
**"the LLM never replaces the grammar — it maps free phrasing onto an
existing, tested command."** T2 confirms/routes; it does not invent
handlers.

Naming note: T0–T4 are ALSO Ada's autonomy ladder
(`ssot.ada-participation.yml`) and L0–L3 are the agent-cascade lanes.
Here T0–T3 are *recognizer-internal* tiers — keep the contexts
separate in docs.

## 3. In-system inventory (what already exists)

| component | where | shape today | gap |
|---|---|---|---|
| `command_lane.py` | ada-voice `backend/` | short turns -> `/v1/systemone` route+entity pick, deterministic time/direction; actuation via tool_runner gates; voice = advisory probe + corpus, text turns enforce (card `use-local-model-for-short-voice-commands-4916da`, 2026-10-10) | systemone calls timed out ~30s every 30-90s (OPS-0605) — no circuit breaker; T2 rung unreliable under load |
| `tg_relay.py` cascade | ada-voice | silence detect -> STT call -> `trivial_gate` transcript filter -> Ada text turn | trivial_gate handles acks/greetings; no command-intent rung — every real command still burns an Ada turn. Card `ada-nest-trivial-gate` adds a local specialist rung (cost/latency, not command routing per se) |
| `devnest-tg-relay` | idc03, `scripts/devnest/devnest-tg-relay.py` | **working T0 in production**: whole-message anchored commands `explain|status <ref>`, `APPROVE|REJECT <ref>`; refusals audited; all board writes via board-api (OPS-0911, `jobs/devnest/2026-10-26-tg-command-router.yml`) | devnest lane only; pattern proves the T0 shape (anchored forms, operand gates, audit log) |
| HA voice | tony-ha, Gemini Live S2S | preferred pipeline is speech-to-speech (`ssot.home-assistant.voice.yml`); device commands go through Gemini tool-calling (flat `tv_command`/`tv_action` tools on ha-live bridge) | every "turn on the light" costs a Live turn; no cheap pre-gate. ha-live has no wake-word; a KWS/command spotter on the mic stream is the only pre-STT option |
| STT lane | idc02 `ada-stt` :8914 | qwen3-asr-0.6b-q8 via audio.cpp, CER 0.212 on 28-clip corpus (`jobs/voice/2026-10-23-local-stt-lane-eval.yml`) | transcripts carry code-switch + transliteration noise — T1 must tolerate it (char n-grams do; token matchers don't) |
| trivial-gate | ada-voice tg_relay | filters trivial transcripts before Ada turn | sibling of where a command rung belongs in the cascade order |

**The gap is uniform:** every lane either pays a provider turn per
command (TG voice->Ada, HA Live tool-call) or has a narrow hardcoded
command set (devnest router). Nobody has the middle rungs — cheap
intent recognition with honest escalation — wired as a shared,
host-agnostic component. That is what this prototype specifies.

## 4. Recommended architecture

**Gated cascade, per-lane placement:**

1. **TG text lanes (ada/mn/devnest):** insert recognizer after STT /
   on raw text, before the Ada turn. devnest router's anchored-command
   discipline becomes the T0 spec; its `audit.jsonl` becomes the
   deflection log.
2. **TG voice notes:** same text cascade on the ada-stt transcript —
   the recognizer doesn't care whether the text was typed or transcribed.
   STT noise is a T1 robustness problem, not a blocker (n-gram sims
   degrade gracefully; threshold absorbs it).
3. **HA voice (Gemini Live):** defer. S2S owns the turn; a pre-gate
   means KWS on the ha-live mic stream — real work, small audience.
   Revisit if Live-turn cost becomes the complaint.
4. **T2 rung:** reuse `command_lane`/systemone once OPS-0605's timeout
   problem has a circuit breaker; until then T2 = escalate-to-provider
   (status quo, no regression).

**Non-negotiables (from the prototype's wrong-fire findings):**

- **Operand gates.** Intents defined by an operand (explain/approve
  need a card ref; Thai device control needs a device noun — bare
  `ปิด` forms media commands like `ปิดเสียง`) must require the operand
  at EVERY tier, not just T0.
- **Vetoes beat scores.** "ช่วย<verb>" (help-me-do-X), "help me X Y",
  "status of <non-card>" look command-adjacent to n-grams but are task
  requests / entity questions. A small veto list checked before
  scoring is cheaper than raising the threshold until recall dies.
- **Margin gate.** Top-1/top-2 similarity gap < ~0.06 = ambiguous =
  escalate, regardless of absolute score.
- **Accept/gray/reject zones.** Gray keeps the candidate for T2
  instead of dropping it — cheaper escalation, better logging.
- **Whole-message anchoring.** "please explain X" is not a command;
   patterns anchor at `^`, phrases match whole-message (devnest rule).

## 5. Prototype + measured results

`docs/prototypes/short-command/` — stdlib-only Python (no numpy /
sklearn / model files), host-agnostic by construction:

- `recognizer.py` — T0 phrase table + anchored operand-gated patterns;
  T1 char 3-5-gram TF-IDF cosine vs per-intent EN/TH prototype phrases
  with accept/gray/reject zones, margin gate, operand gates, vetoes.
- `corpus.jsonl` — 68 items: 34 hard commands, 7 soft (`t2:`)
  commands, 17 pass-through traps, EN+TH.
- `eval/run_eval.py` — report / `--json` / `--sweep` (accept-threshold
  frontier for OPS-0919 real-corpus calibration).

Result (`python3 eval/run_eval.py`):

```
corpus: 68 items (51 commands, 17 pass-through)
wrong-fires: 0   (gate)
deflection: 90.2%   missed hard commands: 0   soft->T2/T3: 5
tiers: {T0: 39, T1: 7}   zones: {accept: 46, reject: 13, gray: 6, veto: 3}
```

Sweep frontier: accept >= 0.38 is the lowest zero-wrong-fire operating
point on this corpus; default ships 0.42 for margin. Below ~0.36 the
synthetic corpus already produces wrong-fires — the threshold is
doing real work, not decoration.

Prototype findings that generalized into §4: the four initial
wrong-fires were all fixable by *structure* (operand gate on
explain/board_action, `ช่วย<verb>` + `help me X Y` + `status of
<non-card>` vetoes, Thai device-noun gate) — not by threshold tuning.
That is the reusable lesson: **wrong-fires are specification bugs,
not similarity bugs.**

## 6. Open questions / next steps

- **OPS-0919 (carded):** recalibrate T1 accept/gray on the real TG
  voice corpus (`~/.local/share/ada-voice-corpus/tg/` refs on idc03,
  qwen3-asr transcripts) — synthetic corpus is a floor, not a
  measurement. `eval/run_eval.py --sweep` is the tool.
- **Production T1:** char n-grams prove the gate shape at $0 deps;
  production should try nomic-embed (already deployed, 768-dim) for
  better paraphrase recall — same zones/gates, swap the similarity
  function. Measure on the OPS-0919 corpus before switching.
- **T2 reliability:** OPS-0605 circuit breaker before command_lane
  can serve as the T2 rung under load.
- **Entity extraction:** prototype is intent-only; slots (device name,
  card ref, delta) are T2's job — matches command_lane's
  route+entity split.
- **Pre-STT:** only if ha-live command latency becomes a complaint;
  KWS on the mic stream is the shape, not a priority.

## 7. References

- KWS cascade: arXiv:1712.03603 (Google, DSP->AP->server)
- ASR-free speech-to-intent: arXiv:2011.04884 (Fluent Speech Commands)
- Audio-to-intent via E2E-ASR subwords: arXiv:2210.12134
- Device-directed speech / false-trigger mitigation: arXiv:2110.04656
- Grammar-constrained ASR hybrid: lalmazan.com/projects/voxa
- Audio-embedding intent matching: ajv009.com/blog/0021
- In-system: `ssot.home-assistant.voice.yml`, `ssot.ada-participation.yml`,
  `ssot.nest-bench.yml`, `jobs/devnest/2026-10-26-tg-command-router.yml`,
  `jobs/voice/2026-10-23-local-stt-lane-eval.yml`,
  `jobs/infrastructure/2026-10-22-chat-local-lane-throughput-tuning.yml`,
  `kb/cheap-agent-cascade.md`, `kb/msg-lane-standard.md`
