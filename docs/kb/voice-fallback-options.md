# Voice fallback options — rainy-day plan for Gemini Live

Researched 2026-10-08. Trigger: Gemini Live becomes unavailable
(outage, quota, deprecation, pricing). Consumers: GEV voice controller
(`gev-gemini` bridge, ws://127.0.0.1:8789, 16kHz PCM + tool calls +
camera frames) and Ada (`ada-pi/backend/realtime_provider.py`).

## Existing seams

- Ada: `RealtimeProvider` ABC (connect / send_audio / send_video /
  send_text_turn / events / close) — only `GeminiLiveProvider`
  implements it today. A second provider is a clean, isolated add.
- GEV: all Live-protocol traffic funnels through `gev-gemini`. One
  protocol adapter there covers every GEV voice surface.

## Options (ranked by fit)

### 1. OpenAI Realtime API — closest hosted drop-in
Speech-to-speech, WebSocket, tool calling, session resumption — same
feature shape. Different event protocol → needs an adapter. Paid.

### 2. huggingface/speech-to-speech — best self-hosted insurance
Modular VAD→STT→LLM→TTS server exposing the **OpenAI Realtime event
set** over WS/WebRTC (`serve` mode, ws://127.0.0.1:8765/v1/realtime).
STT: faster-whisper / Parakeet / Qwen3-ASR (Thai-capable). LLM slot:
any OpenAI-compatible endpoint → vLLM/llama.cpp on omen or idc02.
One Gemini-protocol → Realtime-protocol adapter in `gev-gemini` covers
BOTH hosted OpenAI and this self-hosted stack behind the same path.

### 3. kyutai-labs/moshi — true full-duplex, open weights
7B speech-native, ~200ms on L4 (fits omen). Limits: **English only**,
fixed voices, no tool-calling plumbing (MoshiRAG adds async retrieval,
not function calls). Cannot drive HA. Concept demo, not an Ada
replacement.

### 4. Pipeline frameworks — pipecat / LiveKit Agents / stimm / Voxray
Production VAD→STT→LLM→TTS orchestration, many provider plugins,
telephony. Most flexible, most integration work — a rewrite of the
realtime layer rather than a fallback.

### 5. OpenLive (katipally/LIVINUX) — on-device voice loop
Whole loop in-browser on WebGPU (Silero VAD, Whisper, Kokoro/
Supertonic TTS), BYO brain. Cascaded, not full-duplex. Zero audio
fees; weaker TTS.

## The Thai gap

Gemini Live handles Thai well. Self-hosted STT (Whisper) transcribes
Thai fine; self-hosted TTS (Kokoro/Piper) is weak-to-nonexistent for
Thai. Any local fallback is realistically an English degraded mode
unless Thai TTS is solved separately.

## Recommended posture

| Layer | Choice | Effort |
|---|---|---|
| Insurance adapter | Gemini-protocol → OpenAI-Realtime events in gev-gemini; second `RealtimeProvider` in ada-pi | medium, once |
| Hosted fallback | OpenAI Realtime through the adapter | paid, instant |
| Offline fallback | HF speech-to-speech on idc02/omen + local LLM | medium, no recurring cost |
| Deferred | Moshi / frameworks | revisit when open S2S gains tool use |

## Chaba Nest angle

See kanban card `voice-rainy-day`. Nest contributes the *brain* of a
local cascade (a distilled domain model for the LLM slot — Ada's HA
grammar, Thai/English ops vocabulary, tool-call format) plus warm/cold
distribution of voice-model weights to fleet hosts. The audio
front-end (VAD/STT/TTS) is standard open models, not a Nest deliverable.
A Nest-native full-duplex S2S model is research-scale — not realistic
near-term.
