# PC1 GPU Analysis for BitNet

## PC1 Hardware (from SDXL work)
- **GPU**: NVIDIA (CUDA 12.2+ compatible)
- **Architecture**: Likely x86_64 (standard PC/server)
- **Container Runtime**: Docker with NVIDIA Container Toolkit

## BitNet GPU Requirements
1. **CUDA**: 12.2+ ✓ (PC1 has this)
2. **Model**: BitNet-b1.58-2B-4T (specifically required)
3. **Architecture**: ARM64 only ✗ (PC1 is likely x86_64)

## The Problem
BitNet's GPU kernels (`gpu/bitnet_kernels/`) are:
- Hardcoded for the 2B model architecture
- The 2B model's code generator (`setup_env.py`) raises `NotImplementedError` for x86_64

```python
# From setup_env.py
if repo == "microsoft/BitNet-b1.58-2B-4T":
    if arch == "x86_64":
        raise NotImplementedError("2B model only supports ARM64")
```

## Options for PC1

### Option 1: CPU-only (Working ✓)
Use the working CPU container:
```bash
docker run --rm bitnet:fixed
```
- Model: Falcon3-1B-Instruct-1.58bit
- Speed: ~8 tokens/sec
- Works on x86_64

### Option 2: GPU with 2B model (Blocked ✗)
Requires:
- ARM64 hardware (Apple Silicon, ARM server, Jetson)
- Or upstream BitNet to add x86_64 support for 2B model

### Option 3: Generic llama.cpp GPU (Alternative)
Use standard llama.cpp with CUDA for GGUF models:
```bash
docker run --gpus all -v models:/models ghcr.io/ggerganov/llama.cpp:full-cuda \
  --model /models/falcon3-1b-gguf/ggml-model-i2_s.gguf --prompt "Test"
```

## Recommendation
For PC1's x86_64 + NVIDIA setup:
1. **Use CPU BitNet** for 1.58-bit quantized inference
2. **Use llama.cpp CUDA** for standard GGUF GPU inference
3. **Wait for Microsoft** to add x86_64 support for 2B model GPU kernels

## Files Created
- `Dockerfile.fixed` - Working CPU build (Falcon3-1B)
- `Dockerfile.pc1-gpu` - GPU build template (ARM64 only)
- `test_inference.py` - CPU benchmark script
