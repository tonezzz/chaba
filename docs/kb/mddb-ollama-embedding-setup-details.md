---
category: operations
---

# Implementation Details

### Container Configuration
- **Image**: ollama/ollama:latest
- **Container Name**: ollama
- **GPU Support**: NVIDIA GeForce GTX 1650 (4096MB total)
- **Network**: web_default (Docker network)
- **Restart Policy**: unless-stopped

### Docker Compose Configuration
```yaml
ollama:
  image: ollama/ollama:latest
  container_name: ollama
  restart: unless-stopped
  ports:
    - "11434:11434"
  volumes:
    - ollama-data:/root/.ollama
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
  networks:
    - default
```

### MDDB Environment Configuration
```yaml
environment:
  - MDDB_EMBEDDING_PROVIDER=ollama
  - MDDB_EMBEDDING_API_URL=http://ollama:11434
  - MDDB_EMBEDDING_MODEL=nomic-embed-text
  - MDDB_EMBEDDING_DIMENSIONS=768
```

## Model Information

### nomic-embed-text
- **Model Size**: 274 MB
- **Dimensions**: 768
- **Context Length**: 2048 tokens
- **Family**: nomic-bert
- **Parameter Size**: 137M
- **Quantization**: F16
- **Capabilities**: Embedding generation

### Model Download
```bash
docker exec ollama ollama pull nomic-embed-text
```

## GPU Resource Usage

### Current Allocation
- **Total GPU Memory**: 4096 MB (NVIDIA GeForce GTX 1650)
- **Ollama Usage**: 388 MB (9.5%)
- **Free Memory**: 3213 MB (78.4%)
- **Process**: /usr/lib/ollama/llama-server (PID: 3505946)

### Resource Efficiency
- GPU resources efficiently managed for shared environment
- Sufficient free memory for other GPU services
- Stable performance with low memory footprint

## Integration with MDDB

### Vector Index Status
- **Total Embedded Documents**: 88
- **Total Chunks**: 551
- **Collections Embedded**: 4 (kb-system, kb-development, kb-features, kb-operations)
- **Algorithm**: Flat
- **Distance Metric**: Cosine
- **Quantization**: float32

### Collection Breakdown
- **kb-system**: 27 documents, 153 chunks
- **kb-development**: 15 documents, 90 chunks
- **kb-features**: 42 documents, 268 chunks
- **kb-operations**: 4 documents, 40 chunks

