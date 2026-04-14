#!/bin/bash
# BitNet CPU vs GPU Text Generation Comparison
# Run this from the BitNet repo root after cloning

set -e

PROMPT="Explain quantum computing in simple terms"
MAX_TOKENS=100
MODEL_NAME="bitnet-b1.58-2B-4T"

echo "========================================"
echo "STEP 1: Environment Setup"
echo "========================================"

# Check if we're in the BitNet directory
if [ ! -f "setup_env.py" ]; then
    echo "Cloning BitNet repo..."
    git clone --recursive https://github.com/microsoft/BitNet.git
    cd BitNet
fi

# Create conda environment if it doesn't exist
if ! conda env list | grep -q "bitnet-compare"; then
    echo "Creating conda environment..."
    conda create -n bitnet-compare python=3.9 -y
fi

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate bitnet-compare
pip install -r requirements.txt

echo ""
echo "========================================"
echo "STEP 2: Download Model ($MODEL_NAME)"
echo "========================================"

if [ ! -d "models/$MODEL_NAME" ]; then
    huggingface-cli download "microsoft/BitNet-b1.58-2B-4T-gguf" --local-dir "models/$MODEL_NAME"
    huggingface-cli download "microsoft/bitnet-b1.58-2B-4T-bf16" --local-dir "models/$MODEL_NAME-bf16"
fi

echo ""
echo "========================================"
echo "STEP 3: CPU Inference (bitnet.cpp)"
echo "========================================"

# Build if needed
if [ ! -f "build/Release/bitnet.dll" ] && [ ! -f "build/libbitnet.so" ]; then
    python setup_env.py -md "models/$MODEL_NAME" -q i2_s
fi

echo "Running CPU generation..."
CPU_START=$(date +%s.%N)
python run_inference.py \
    -m "models/$MODEL_NAME/ggml-model-i2_s.gguf" \
    -p "$PROMPT" \
    -n $MAX_TOKENS \
    -t 4 \
    -temp 0.8 2>&1 | tee /tmp/cpu_output.txt
CPU_END=$(date +%s.%N)
CPU_DURATION=$(echo "$CPU_END - $CPU_START" | bc)

echo ""
echo "CPU Time: ${CPU_DURATION}s"

echo ""
echo "========================================"
echo "STEP 4: GPU Inference (CUDA Kernels)"
echo "========================================"

cd gpu

# Install GPU deps and build
pip install -r requirements.txt
if [ ! -f bitnet_kernels/bitnet_cuda*.so ]; then
    cd bitnet_kernels && bash compile.sh && cd ..
fi

# Convert model for GPU if needed
if [ ! -f "../checkpoints/model.pt" ]; then
    mkdir -p ../checkpoints
    python ../convert_safetensors.py \
        --safetensors_file "../models/$MODEL_NAME-bf16/model.safetensors" \
        --output ../checkpoints/model_state.pt \
        --model_name 2B
    python convert_checkpoint.py --input ../checkpoints/model_state.pt
    rm ../checkpoints/model_state.pt
fi

echo "Running GPU generation..."
GPU_START=$(date +%s.%N)
python generate.py \
    ./checkpoints/ \
    --prompt "$PROMPT" \
    --max_tokens $MAX_TOKENS \
    --temperature 0.8 2>&1 | tee /tmp/gpu_output.txt
GPU_END=$(date +%s.%N)
GPU_DURATION=$(echo "$GPU_END - $GPU_START" | bc)

echo ""
echo "GPU Time: ${GPU_DURATION}s"

cd ..

echo ""
echo "========================================"
echo "STEP 5: Comparison Summary"
echo "========================================"

SPEEDUP=$(echo "scale=2; $CPU_DURATION / $GPU_DURATION" | bc)
echo "Prompt: '$PROMPT'"
echo "Max Tokens: $MAX_TOKENS"
echo ""
echo "CPU Time: ${CPU_DURATION}s"
echo "GPU Time: ${GPU_DURATION}s"
echo "Speedup: ${SPEEDUP}x"

echo ""
echo "========================================"
echo "Running E2E Benchmark"
echo "========================================"
python utils/e2e_benchmark.py -m "models/$MODEL_NAME/ggml-model-i2_s.gguf" -n 128 -p 512 -t 4
