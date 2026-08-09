# LLM Container Configuration and Performance

## What it is

Configuration details and performance characteristics for the `thai-legal-inference` Docker container that runs llama.cpp server for local LLM inference on NVIDIA GTX 1650 GPU.

## Context

The system uses Docker (not Podman) for container runtime. Podman is installed but fails with `crun not found` runtime error. The LLM container uses llama.cpp server with model aliasing to serve different GGUF models via a single endpoint.

## Technical Details

### Container Runtime
- **Runtime**: Docker (not Podman)
- **Podman Status**: Installed but non-functional due to `crun not found` runtime error
- **Container Name**: `thai-legal-inference`
- **Configuration File**: `docker-compose.yml`

### Model Alias Configuration
The `thai-legal-inference` container uses the `--alias` parameter in docker-compose.yml to define which models are available for serving:

```yaml
command: >
  --alias Phi-3-mini-4k-instruct-q4=/data/gguf/Phi-3-mini-4k-instruct-q4.gguf
```

**Important**: Changing the alias parameter requires container recreation to take effect:
```bash
docker compose down
docker compose up -d
```

### Model Naming Convention
When using llama.cpp server with alias configuration:
- **Alias name**: Used only for container configuration (e.g., `Phi-3-mini-4k-instruct-q4`)
- **API model name**: Must use the full GGUF filename in API calls (e.g., `Phi-3-mini-4k-instruct-q4`)
- **Example API call**:
  ```bash
  curl http://localhost:8001/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{
      "model": "Phi-3-mini-4k-instruct-q4",
      "messages": [{"role": "user", "content": "Hello"}]
    }'
  ```

### Current Model Configuration
- **Active Model**: Phi-3-mini-4k-instruct-q4 (2.3GB)
- **Inactive Model**: thai-legal-gemma-4b-cpt.Q4_K_M.gguf (5.0GB) - removed from alias due to GPU memory constraints
- **GPU**: NVIDIA GTX 1650 (4GB VRAM)
- **API Endpoint**: `http://tony-omen.local:8001/v1/chat/completions`

## Performance Characteristics

### Model Loading Time
- **Phi-3-mini-4k-instruct-q4**: ~45 seconds to load on first request after container start
- **Impact**: First API call after container restart will experience significant delay
- **Mitigation**: Container stays running, subsequent requests do not incur loading time

### Token Generation Performance
- **Hardware**: NVIDIA GTX 1650 with 4GB VRAM
- **GPU Utilization**: 62% during inference
- **Token Generation Speed**: ~2.6 tokens/second
- **Assessment**: Very slow performance, suitable only for low-volume inference
- **Use Case**: Acceptable for Yomi summarization (batch processing), not suitable for real-time chat

### GPU Memory Usage
- **Phi-3-mini-4k-instruct-q4**: Uses significant portion of 4GB VRAM
- **Thai Legal Model**: 5GB model exceeds available VRAM, cannot load
- **Constraint**: Only one model can be loaded at a time due to VRAM limitations

## Usage

### Check Loaded Models
```bash
curl http://tony-omen.local:8001/v1/models | jq .
```

### Check GPU Memory Usage
```bash
docker exec thai-legal-inference nvidia-smi
```

### Check Llama Server Health
```bash
curl http://tony-omen.local:8001/health
```

### Change Model Alias
1. Edit `docker-compose.yml` to update the `--alias` parameter
2. Recreate container:
   ```bash
   docker compose down
   docker compose up -d
   ```
3. Wait for model to load (~45 seconds)
4. Verify with API call using new model name

## Troubleshooting

### Podman Fails with "crun not found"
**Issue**: Podman container runtime fails to start containers
**Root Cause**: Missing or incompatible crun runtime
**Solution**: Use Docker instead of Podman for this system
**Status**: Docker is the working runtime, Podman is non-functional

### Model Not Available After Alias Change
**Issue**: API returns "model not found" after changing alias
**Root Cause**: Container not recreated after alias change
**Solution**: Must run `docker compose down && docker compose up -d` for alias changes to take effect

### First API Call Very Slow
**Issue**: First request after container start takes ~45 seconds
**Root Cause**: Model loading time on first request
**Solution**: Expected behavior, subsequent requests will be faster
**Mitigation**: Keep container running to avoid reloads

### Slow Token Generation
**Issue**: ~2.6 tokens/second generation speed
**Root Cause**: GTX 1650 is entry-level GPU with limited compute performance
**Current Status**: Acceptable for batch processing (Yomi summarization)
**Potential Solutions**:
  - Upgrade GPU for better performance
  - Use smaller quantized models
  - Reduce request volume or batch processing

### GPU Memory Exhaustion
**Issue**: Cannot load models larger than 4GB
**Root Cause**: GTX 1650 has only 4GB VRAM
**Current Workaround**: Use Phi-3-mini (2.3GB) instead of Thai Legal model (5GB)
**Potential Solutions**:
  - Upgrade GPU with more VRAM
  - Use smaller models
  - Offload some layers to CPU (slower but allows larger models)

## Related Documentation

- `docs/kb/yomi.md` - Yomi LINE web app with LLM integration details
- `docs/kb/yomi-summary-corruption.md` - LLM summarization quality issues
- `docs/kb/yomi-daily-summaries.md` - Daily summary generation using Phi-3 model
- `chaba/stacks/web/docker-compose.yml` - Container configuration with alias parameter

## Tags

llm, docker, llama.cpp, gpu, phi-3, model-configuration, performance, gtx-1650, container-runtime, alias
