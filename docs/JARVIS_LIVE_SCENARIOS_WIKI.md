# Jarvis Live API Scenarios

## Overview

Jarvis supports 4 operational scenarios for voice/text interaction, controlled by model capabilities and environment variables.

## The 4 Scenarios

| Scenario | Name | Input | Output | Use Case |
|----------|------|-------|--------|----------|
| 1 | **Non-Live Fallback** | Audio | Text (TTS) | Legacy mode using sidecar STT + Gemini standard API + TTS |
| 2 | **Live Text-Only** | Text | Text | Chat interface without voice |
| 3 | **Live Voice-In-Text-Out** | Audio | Text | Voice commands, transcription needed |
| 4 | **Live Full-Voice** | Audio | Audio | Natural voice conversation |

## Scenario Detection

Scenarios are auto-detected based on model name:

- `gemini-2.5-flash-native-audio-latest` → **Scenario 4** (full voice)
- `gemini-3.1-flash-lite` → **Scenario 3** (voice in, text out)
- Other models → **Scenario 2** (text only)

## Forcing Scenario 3 (Text-Only Output)

To force a native audio model to respond with text instead of voice:

```bash
JARVIS_LIVE_FORCE_TEXT_ONLY=true
```

Set this in Portainer: **Stacks → idc1-assistance → Editor → Environment Variables**

### When to Use

- Testing/debugging voice input without audio output
- Preferring text responses for accuracy review
- Environments where audio playback is problematic

### Technical Details

When `JARVIS_LIVE_FORCE_TEXT_ONLY=true`:
- Uses `response_modalities=["TEXT"]` instead of `["AUDIO"]`
- Enables `input_audio_transcription` to show user transcripts
- Audio is still sent to Gemini (voice input works)
- Response comes as text (no TTS needed)

## Configuration Reference

### LiveConnectConfig Types

**Full Voice (Scenario 4):**
```python
LiveConnectConfig(
    response_modalities=["AUDIO"],
    speech_config=SpeechConfig(
        voice_config=VoiceConfig(
            prebuilt_voice_config=PrebuiltVoiceConfig(voice_name="Aoede")
        )
    ),
)
```

**Voice-In-Text-Out (Scenario 3):**
```python
LiveConnectConfig(
    response_modalities=["TEXT"],
    input_audio_transcription=AudioTranscriptionConfig(),
)
```

### Related Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `JARVIS_LIVE_FORCE_TEXT_ONLY` | `false` | Force text-only responses for native audio models |
| `JARVIS_LIVE_PROBE_ON_CONNECT` | `false` | Probe all models on each connection |
| `JARVIS_LIVE_MODEL_CACHE_PATH` | `/data/jarvis_live_model_cache.json` | Cache working model/config |
| `JARVIS_GOOGLE_TTS_VOICE` | (Chirp3 HD) | Default voice for TTS fallback |

## Troubleshooting

### No Audio Output

Check if `speech_config` is present in the LiveConnectConfig. Native audio models require `speech_config` to produce audio.

### Gibberish Transcriptions

Sidecar STT has been disabled for native audio models. Use Gemini's native `input_audio_transcription` instead.

### Switching Scenarios

Clear the model cache after changing config:
```bash
docker exec idc1-assistance-core-jarvis-backend-1 rm -f /data/jarvis_live_model_cache.json
```

## See Also

- `jarvis/websocket/session.py` - Implementation
- Google GenAI SDK - `types.LiveConnectConfig`
