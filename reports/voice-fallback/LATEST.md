# Voice-fallback benchmark — latest results

Rendered 2026-11-26 11:49 UTC by `scripts/voice-bench/report.py`.

| combo | stt | llm | tts | orchestrator | host_labels | n | ok | mean ttfa ms | mean total ms | mean wer | tool exact/partial/none |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ? | ? | ? | ? | ? | — | 0 | 0 | — | — | — | 0/0/0 |
| cascade-whisper-piper | faster-whisper | ollama-phi3 (phi3-gguf:latest) | piper | voice-bench-pipeline | gpu | 30 | 30 | 11776.37 | 19718.12 | 0.07 | 12/5/13 |
| gemini-baseline | gemini-live-native | gemini-live | gemini-live-native | gev-gemini-client-shape | — | 20 | 20 | 330.35 | 6222.95 | 0.01 | 7/4/3 |
| gemini-live-extended-thinking | gemini-live-native | gemini-live-extended-thinking | gemini-live-native | gev-gemini-client-shape | — | 20 | 20 | 10.05 | 10864.5 | 0.01 | 8/6/0 |
| hf-s2s | faster-whisper-small | ollama-qwen2.5-1.5b | qwen3-ggml | hf-speech2speech | gpu | 20 | 20 | 75827.53 | 132645.2 | 0.11 | 0/1/13 |
| moshi | moshi-full-duplex | kyutai-moshiko-7b | moshi-full-duplex | moshi-adapter | gpu | 20 | 10 | 50563.8 | 218073.7 | 1.0 | 0/0/7 |

Tool column is exact/partial/none matches; see `scripts/voice-bench/results/` for raw JSON.
