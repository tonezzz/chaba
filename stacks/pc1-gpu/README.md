# PC1 GPU Stack - Local LLM Testing

Quick proof of concept for running Gemma 4B on local GPU.

## Phase 1: Python POC (Immediate)

### Requirements
```bash
pip install torch transformers accelerate
```

### Run Test
```bash
cd stacks/pc1-gpu
python test_gemma.py
```

This will:
- Check CUDA/GPU availability
- Download `google/gemma-4b-it` (~8GB)
- Run 3 test generations
- Show tokens/second performance

## Phase 2: vLLM API (Production)

### Start vLLM
```bash
docker-compose up -d vllm
```

**First run:** Downloads model (~2-3 minutes)  
**Subsequent runs:** Instant startup

### Test API
```bash
# Wait for health check
curl http://localhost:8000/health

# Run test
python test_vllm.py
```

### Manual API Call
```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "google/gemma-4b-it",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

## Configuration

| Service | Port | Purpose |
|---------|------|---------|
| vLLM | 8000 | OpenAI-compatible API |
| Ollama | 11434 | Alternative CLI (optional) |

## Integration

Use with AutoAgent/MCP:
```python
# In your .env or config
API_BASE_URL=http://localhost:8000/v1
COMPLETION_MODEL=google/gemma-4b-it
# No API key needed for local vLLM
```

## GPU Requirements

| Model | VRAM | Notes |
|-------|------|-------|
| gemma-4b-it | ~8GB | Fits on RTX 3070+ |
| gemma-7b-it | ~14GB | Requires RTX 3090/4090 |

## Troubleshooting

**Out of memory:** Lower `gpu-memory-utilization` in docker-compose.yml  
**Slow first run:** Model downloads on first startup  
**CUDA errors:** Ensure NVIDIA Container Toolkit installed:
```bash
docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi
```
