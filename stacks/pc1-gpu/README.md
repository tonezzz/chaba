# PC1 GPU Stack

Dedicated stack for GPU-accelerated MCP services, primarily `mcp-cuda` for SDXL image generation.

## Services

- **mcp-cuda** - GPU-accelerated ML utilities and SDXL image generation
  - Port: 8057
  - GPU: NVIDIA CUDA with 1 GPU reservation
  - Models: Local SDXL weights from `C:\chaba\.models\sdxl`

## Usage

```bash
# Start GPU stack
docker-compose --file docker-compose.yml up -d

# Check health
curl http://localhost:8057/health

# Test SDXL generation
curl -X POST http://localhost:8057/invoke \
  -H "Content-Type: application/json" \
  -d '{"tool":"imagen_models","arguments":{}}'
```

## Cross-Host Access

The GPU service is designed to be accessed from other hosts:

### From pc2-worker
Copy the remote configuration:
```bash
# On pc2-worker, add pc1 GPU access
cp 1mcp.json.pc1-gpu 1mcp.json.pc1-gpu.backup

# Merge with existing 1mcp.json or use as standalone
```

Configuration file (`pc2-worker/1mcp.json.pc1-gpu`):
```json
{
  "mcpServers": {
    "pc1-mcp-cuda": {
      "transport": "streamableHttp",
      "url": "http://pc1.vpn:8057/mcp",
      "tags": ["pc1", "cuda", "sdxl", "remote", "gpu"],
      "enabled": true
    }
  }
}
```

### Testing Cross-Host Access
```bash
# From pc2-worker, test pc1 GPU service
curl -X POST http://pc1.vpn:8057/invoke \
  -H "Content-Type: application/json" \
  -d '{"tool":"imagen_models","arguments":{}}'

# Test image generation
curl -X POST http://pc1.vpn:8057/invoke \
  -H "Content-Type: application/json" \
  -d '{"tool":"imagen_job_create","arguments":{"prompt":"A test image","width":512,"height":512}}'
```

### Environment Setup
```bash
# Copy environment file
cp .env.example .env

# Adjust paths as needed
# PC1_SDXL_MODEL_HOST_DIR=C:/chaba/.models/sdxl
```

## Network

- **Network**: `pc1-gpu-net` (172.20.0.0/16)
- **VPN Access**: Available via `pc1.vpn:8057`
- **GPU Access**: Direct `/dev/dri` device mapping

## Requirements

- NVIDIA GPU with CUDA support
- Docker with NVIDIA Container Toolkit
- Local SDXL model weights in `C:\chaba\.models\sdxl`
