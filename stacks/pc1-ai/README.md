# PC1 AI Stack

Dedicated stack for AI/ML services, model gateways, and image generation.

## Services

- **mcp-glama** - Glama model gateway
  - Port: 7241 → 8014
  - Purpose: LLM model access and management

- **mcp-github-models** - GitHub Models API gateway
  - Port: 7242 → 8015
  - Purpose: GitHub-hosted AI models access

- **mcp-openai-gateway** - OpenAI API proxy
  - Port: 8181
  - Purpose: OpenAI API integration and proxy

- **ollama** - Local LLM server
  - Port: 11435 → 11434
  - Purpose: Local AI model hosting

- **mcp-imagen-light** - Image generation adapter
  - Port: 8020
  - Purpose: SDXL image generation via GPU stack

## Usage

```bash
# Start AI stack
docker-compose --file docker-compose.yml up -d

# Check service health
curl http://localhost:7241/health  # Glama
curl http://localhost:7242/health  # GitHub Models
curl http://localhost:8181/health  # OpenAI Gateway
curl http://localhost:11435/health # Ollama
curl http://localhost:8020/health  # Imagen

# Test model gateway
curl -X POST http://localhost:7241/invoke \
  -H "Content-Type: application/json" \
  -d '{"tool":"chat_completion","arguments":{"model":"llama3.1","messages":[{"role":"user","content":"Hello"}]}}'

# Test image generation
curl -X POST http://localhost:8020/invoke \
  -H "Content-Type: application/json" \
  -d '{"tool":"generate_image","arguments":{"prompt":"A beautiful sunset","steps":20}}'
```

## Cross-Host Access

The AI services are designed to be accessible from other hosts:

### From pc2-worker or other hosts
```json
// 1mcp.json configuration
{
  "mcpServers": {
    "pc1-mcp-glama": {
      "transport": "streamableHttp",
      "url": "http://pc1.vpn:7241/mcp",
      "tags": ["pc1", "glama", "llm", "remote"],
      "enabled": true
    },
    "pc1-mcp-github-models": {
      "transport": "streamableHttp",
      "url": "http://pc1.vpn:7242/mcp",
      "tags": ["pc1", "github-models", "remote"],
      "enabled": false
    },
    "pc1-mcp-openai-gateway": {
      "transport": "streamableHttp",
      "url": "http://pc1.vpn:8181/mcp",
      "tags": ["pc1", "openai", "remote"],
      "enabled": true
    },
    "pc1-ollama": {
      "transport": "streamableHttp",
      "url": "http://pc1.vpn:11435/mcp",
      "tags": ["pc1", "ollama", "llm", "remote"],
      "enabled": true
    },
    "pc1-mcp-imagen-light": {
      "transport": "streamableHttp",
      "url": "http://pc1.vpn:8020/mcp",
      "tags": ["pc1", "imagen", "remote"],
      "enabled": true
    }
  }
}
```

### Environment Setup
```bash
# Copy environment file
cp .env.example .env

# Set API keys
# GLAMA_API_KEY=your_glama_api_key
# GITHUB_TOKEN=your_github_token
# OPENAI_API_KEY=your_openai_api_key
```

## Network

- **Network**: `pc1-ai-net` (172.24.0.0/16)
- **VPN Access**: Available via `pc1.vpn` endpoints
- **GPU Integration**: Imagen connects to pc1-gpu stack

## Features

### Model Gateways
- **Glama**: Multiple LLM provider access
- **GitHub Models**: GitHub-hosted AI models
- **OpenAI Gateway**: OpenAI API proxy and management

### Local AI
- **Ollama**: Local LLM hosting with GPU support
- **Model Management**: Download, list, and run models
- **Performance**: Optimized for local inference

### Image Generation
- **SDXL Integration**: Connects to GPU stack for generation
- **FastAPI Adapter**: RESTful image generation API
- **Progress Tracking**: Real-time generation progress
- **Output Management**: Persistent image storage

## Requirements

- API keys for external services (Glama, GitHub, OpenAI)
- Network access to pc1-gpu stack for image generation
- Sufficient memory for AI models
- GPU access for accelerated inference

## Data Persistence

- **ollama-data**: Downloaded AI models and caches
- **mcp-imagen-light-images**: Generated images and outputs

## Security Considerations

- **API Keys**: Store securely in environment variables
- **Network Access**: Consider VPN-only access for sensitive models
- **Model Privacy**: Local models keep data on-premise
- **Resource Limits**: Monitor GPU and memory usage

## Integration

This stack integrates with:
- **pc1-gpu** - SDXL image generation acceleration
- **pc1-db** - Vector search for AI embeddings
- **pc1-devops** - AI model deployment workflows
- **pc2-worker** - Remote AI service access

## Model Management

### Ollama Commands
```bash
# List available models
docker exec pc1-ai-ollama ollama list

# Pull new model
docker exec pc1-ai-ollama ollama pull llama3.1

# Run model
docker exec pc1-ai-ollama ollama run llama3.1
```

### Gateway Configuration
- **Model Selection**: Choose appropriate model per task
- **Load Balancing**: Distribute requests across providers
- **Fallback**: Configure backup model providers
- **Rate Limiting**: Manage API usage and costs
