# PC1 LLM Stack - Local GPU LLM Testing

Quick proof of concept for running local LLMs on PC1 GPU (GTX 1650).
Currently using Qwen 0.5B (public model). Gemma requires HuggingFace auth.

## Phase 1: Python POC (Immediate)

### Requirements
```bash
pip install torch transformers accelerate
```

### Run Test
```bash
cd stacks/pc1-llm
python test_gemma.py
```

This will:
- Check CUDA/GPU availability
- Download `Qwen/Qwen2.5-0.5B-Instruct` (~1GB)
- Run 3 test generations
- Show tokens/second performance

## Phase 2: Ollama (Alternative)

```bash
# Start Ollama
docker-compose --profile ollama up -d

# Pull Qwen model (one time)
docker exec pc1-ollama ollama pull qwen2.5:0.5b

# Test
docker exec pc1-ollama ollama run qwen2.5:0.5b "Say hello in 5 words"

# Or use API
curl http://localhost:11434/api/generate -d '{
  "model": "qwen2.5:0.5b",
  "prompt": "Hello!",
  "stream": false
}'
```

## Phase 3: vLLM API (Production)

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
