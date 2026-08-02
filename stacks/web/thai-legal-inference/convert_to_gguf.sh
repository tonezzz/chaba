#!/bin/bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q build-essential git python3-pip cmake

OUT_DIR=/workspace/out
mkdir -p "$OUT_DIR"

cd /workspace
if [ ! -d llama.cpp ]; then
  git clone --depth 1 https://github.com/ggml-org/llama.cpp.git
fi
cd llama.cpp

# build llama-quantize (CPU target is enough)
cmake -B build -DLLAMA_BUILD_EXAMPLES=ON -DLLAMA_BUILD_SERVER=OFF -DLLAMA_BUILD_TESTS=OFF
cmake --build build --target llama-quantize -j$(nproc)
LLAMA_QUANTIZE=build/bin/llama-quantize

# install gguf writer and conversion deps
pip install -q -e gguf-py
pip install -q sentencepiece protobuf safetensors numpy tqdm colorama transformers tiktoken

MODEL_DIR=/root/.cache/huggingface/hub/models--Phonsiri--Thai-Legal-Gemma-4B-CPT/snapshots/464e5a6769063e36ca2664c7013b0dd3427e8d61

python convert_hf_to_gguf.py "$MODEL_DIR" \
  --outfile "$OUT_DIR/thai-legal-gemma-4b-cpt.f16.gguf" \
  --outtype f16

"$LLAMA_QUANTIZE" \
  "$OUT_DIR/thai-legal-gemma-4b-cpt.f16.gguf" \
  "$OUT_DIR/thai-legal-gemma-4b-cpt.Q4_K_M.gguf" \
  Q4_K_M

rm "$OUT_DIR/thai-legal-gemma-4b-cpt.f16.gguf"

echo "GGUF ready: $OUT_DIR/thai-legal-gemma-4b-cpt.Q4_K_M.gguf"
ls -lh "$OUT_DIR/thai-legal-gemma-4b-cpt.Q4_K_M.gguf"
