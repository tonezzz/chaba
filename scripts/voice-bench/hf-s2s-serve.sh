#!/usr/bin/env bash
# Launch huggingface/speech-to-speech in serve mode for the `hf-s2s` combo:
#   STT  faster-whisper (multilingual "small" — Thai-capable) on CUDA
#   LLM  OpenAI-compatible chat-completions endpoint (ollama/vLLM)
#   TTS  repo default (qwen3, ggml backend)
#   VAD  silero (default)
# Listens on ws://127.0.0.1:8765/v1/realtime
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
BIN="${S2S_BIN:-$ROOT/.venv-s2s/bin/speech-to-speech}"
LLM_BASE_URL="${S2S_LLM_BASE_URL:-http://100.75.102.88:11434/v1}"
# phi3-gguf does not support tools on ollama (400 "does not support tools");
# qwen3 thinks before calling (slow); qwen2.5:1.5b is the smallest ollama
# model that emits native tool_calls without a reasoning preamble.
LLM_MODEL="${S2S_LLM_MODEL:-qwen2.5:1.5b}"

# GTX1650 4GB is already ~2.2GB occupied by ollama's llama-server — run the
# whole pipeline CPU-side so qwen3-ggml doesn't OOM on cudaMalloc.
export CUDA_VISIBLE_DEVICES="${S2S_CUDA_VISIBLE_DEVICES:-}"

# qwentts-cpp (qwen3 ggml TTS) is built against CUDA 12 while torch pulls
# CUDA 13 libs — put the pip-installed cu12 runtime on the loader path.
NV="$ROOT/.venv-s2s/lib/python3.12/site-packages/nvidia"
export LD_LIBRARY_PATH="${NV}/cuda_runtime/lib:${NV}/cublas/lib:${NV}/cudnn/lib:${NV}/nvrtc/lib:${LD_LIBRARY_PATH:-}"

exec "$BIN" serve \
  --stt faster-whisper \
  --faster_whisper_stt_model_name "${S2S_WHISPER_MODEL:-small}" \
  --faster_whisper_stt_device "${S2S_WHISPER_DEVICE:-cpu}" \
  --faster_whisper_stt_compute_type auto \
  --faster_whisper_stt_gen_language auto \
  --llm_backend chat-completions \
  --responses_api_base_url "$LLM_BASE_URL" \
  --responses_api_api_key ollama \
  --model_name "$LLM_MODEL" \
  --stream_batch_sentences 1 \
  --tts "${S2S_TTS:-qwen3}" \
  --qwen3_tts_ggml_quantization "${S2S_TTS_QUANT:-Q4_K_M}" \
  --host 127.0.0.1 --port 8765 \
  --log_level info --log_transcripts
