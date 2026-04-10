# Jarvis Live Scenarios

Single source of truth for the 4 Jarvis operation scenarios based on model capabilities.

## Overview

Jarvis supports **4 distinct scenarios** for user interaction, determined by the Gemini Live model's capabilities:

| # | Scenario | Model | Input | Output | TTS? | Use Case |
|---|----------|-------|-------|--------|------|----------|
| 1 | **Smart Fallback** | Any | Voice → STT | HTTP Gemini → TTS | ✅ | Live unavailable / Rate limited |
| 2 | **Live Text-Only** | `gemini-2.5-flash`, `gemini-2.5-pro` | Text | Text | ❌ | Text chat with fast Live connection |
| 3 | **Live Voice-In, Text-Out** | `gemini-3.1-flash-lite` | Audio | Text → **TTS speaks** | ✅ | Voice chat with cost-efficient model |
| 4 | **Live Full Voice** | `gemini-2.5-flash-native-audio-*` | Audio | Audio | ❌ | Real-time voice conversation |

## Scenario Details

### 1. Smart Fallback (No Live)

**When:** Gemini Live API unavailable, rate-limited, or no working model found.

**Flow:**
```
Voice → Sidecar STT → HTTP Gemini API → TTS → Audio Output
```

**Implementation:** `WebSocketSession._handle_smart_fallback_mode()`

**Features:**
- Sidecar STT for voice input transcription
- HTTP Gemini API for responses (`generate_content`)
- Google TTS (Chirp3 HD) for audio output
- Exponential backoff for rate limit retries

---

### 2. Live Text-Only

**When:** Using non-audio models in Live mode (text chat only).

**Models:**
- `gemini-2.5-flash`
- `gemini-2.5-pro`
- `gemini-2.0-flash-*`
- `gemini-flash-*`

**Flow:**
```
Text → Live WebSocket → Gemini Live → Text Response
```

**Capabilities:**
- Fast bidirectional text chat
- No audio input/output support
- Suitable for text-only interfaces

**Implementation:** `_ws_to_gemini_with_session()` sends `send_realtime_input(text=...)`

---

### 3. Live Voice-In, Text-Out

**When:** Using `gemini-3.1-flash-lite` - supports audio input but only text output.

**Models:**
- `gemini-3.1-flash-lite` ⭐ Recommended for cost-efficient voice

**Flow:**
```
Voice → Live WebSocket → Gemini Live (transcribes) → Text Response → TTS → Audio Output
```

**Capabilities:**
- Audio input: Gemini Live transcribes speech
- Text output: Model responds with text
- **TTS required**: Backend synthesizes audio output (Chirp3 HD)
- Cost-efficient for high-volume voice applications

**Implementation:**
- `_ws_to_gemini_with_session()` sends `send_realtime_input(audio=...)`
- `_gemini_to_ws_with_session()` detects `supports_voice_input=True` + `supports_voice_output=False`
- `_speak_live_response()` triggers TTS for text responses

---

### 4. Live Full Voice

**When:** Using native-audio models that support both audio input and output.

**Models:**
- `gemini-2.5-flash-native-audio-latest` ⭐ Recommended
- `gemini-2.5-flash-native-audio-preview-12-2025`
- `lyria-realtime-exp`

**Flow:**
```
Voice → Live WebSocket → Gemini Live → Audio Response
```

**Capabilities:**
- Real-time bidirectional audio streaming
- No TTS needed - model generates audio directly
- Lowest latency for voice conversations
- Most natural voice interactions

**Implementation:**
- `_ws_to_gemini_with_session()` sends `send_realtime_input(audio=...)`
- `_gemini_to_ws_with_session()` forwards `output_audio` chunks to frontend

## Capability Detection

The `LiveCapabilities` class (`jarvis/websocket/session.py`) determines model capabilities:

```python
class LiveCapabilities:
    def __init__(self, model: str):
        m = str(model or "").lower()
        self.has_audio_input = "native-audio" in m or "3.1-flash-lite" in m
        self.has_audio_output = "native-audio" in m
        # ...
    
    @property
    def scenario(self) -> str:
        if self.has_audio_input and self.has_audio_output:
            return "live-full-voice"  # Scenario 4
        elif self.has_audio_input:
            return "live-voice-in-text-out"  # Scenario 3
        else:
            return "live-text-only"  # Scenario 2
```

## Configuration Selection

Based on capabilities, Jarvis selects appropriate `LiveConnectConfig`:

| Scenario | Config Type | Response Modalities | Notes |
|----------|-------------|---------------------|-------|
| 1 (Smart Fallback) | N/A | N/A | Uses HTTP API, not Live |
| 2 (Text-Only) | TEXT | `["TEXT"]` | Standard text configs |
| 3 (Voice-In, Text-Out) | TEXT | `["TEXT"]` | TEXT configs but audio input accepted |
| 4 (Full Voice) | AUDIO | `["AUDIO"]` or `["AUDIO", "TEXT"]` | AUDIO configs for native audio |

## Environment Variables

Key variables affecting scenario selection:

| Variable | Purpose | Affects Scenario |
|----------|---------|-------------------|
| `GEMINI_LIVE_MODEL` | Preferred Live model | 2, 3, 4 |
| `JARVIS_LIVE_PROBE_ON_CONNECT` | Probe for working model on connect | 2, 3, 4 |
| `JARVIS_DISABLE_GEMINI_LIVE` | Force Scenario 1 (Smart Fallback) | 1 |
| `JARVIS_SIDECAR_STT_MODEL` | STT model for Scenario 1 | 1 |
| `GOOGLE_TTS_API_KEY` | Required for TTS in Scenarios 1 & 3 | 1, 3 |
| `JARVIS_GOOGLE_TTS_LANGUAGE` | TTS language (default: en-US) | 1, 3 |

## Model Probe Order

When `JARVIS_LIVE_PROBE_ON_CONNECT=true`, Jarvis probes models in this order:

1. `GEMINI_LIVE_MODEL` (if set)
2. `gemini-3.1-flash-lite` ⭐ (Scenario 3)
3. `gemini-2.5-flash-native-audio-latest` ⭐ (Scenario 4)
4. `gemini-2.5-flash-native-audio-preview-12-2025` (Scenario 4)
5. `lyria-realtime-exp` (Scenario 4)

Models are tested with appropriate configs based on detected capabilities.

## Logging

Jarvis logs the detected scenario during connection:

```
[live-full-voice] Using AUDIO configs for gemini-2.5-flash-native-audio-latest
[live-voice-in-text-out] Using TEXT configs for gemini-3.1-flash-lite (needs TTS for output)
[live-text-only] Using TEXT configs for gemini-2.5-flash
```

Audio sending also logs capabilities:
```
Live sending audio pcm_bytes=256 model=gemini-3.1-flash-lite scenario=live-voice-in-text-out voice_in=True voice_out=False
```

## Choosing a Scenario

### Use Scenario 1 (Smart Fallback) when:
- Gemini API rate limits exceeded
- Live API unavailable (500 errors)
- Testing/debugging with reliable HTTP API
- Prefer HTTP API responses over Live

### Use Scenario 2 (Live Text-Only) when:
- Text-only interface (no voice)
- Fast text chat needed
- Voice models unavailable or expensive

### Use Scenario 3 (Live Voice-In, Text-Out) when:
- Cost-efficient voice interactions needed
- `gemini-3.1-flash-lite` available
- Acceptable to have TTS-synthesized responses
- High-volume voice applications

### Use Scenario 4 (Live Full Voice) when:
- Most natural voice experience needed
- Lowest latency required
- Native audio models available
- Best voice quality desired

## Future Scenarios

Potential scenarios not yet implemented:

### 5. Live Multi-Modal (Video Input)
- Video frames from camera → Live model
- Requires frontend camera capture + frame encoding

### 6. Live with Tool Use
- Function calling within Live session
- Tool execution loop during conversation

### 7. Live with Barge-In
- Detect user speech during model response
- Cancel ongoing response, process new input

### 8. Hybrid: Live Voice + HTTP for Complex Tasks
- Use Live for real-time voice chat
- Switch to HTTP API for tasks needing tool use / search / long context

## References

- Implementation: `jarvis/websocket/session.py`
  - `LiveCapabilities` class
  - `_handle_smart_fallback_mode()` - Scenario 1
  - `_ws_to_gemini_with_session()` - Scenarios 2, 3, 4 input
  - `_gemini_to_ws_with_session()` - Scenarios 2, 3, 4 output
  - `_speak_live_response()` - TTS for Scenario 3
- Configuration: `docs/CONFIG.md`
- Architecture: `ARCHITECTURE.md`
