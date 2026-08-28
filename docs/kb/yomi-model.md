---
category: operations
---

# Model Configuration

### Current Summarization Model
- **Primary Model**: Gemini API (gemma-4-31b-it) with language detection (Thai/English/mixed)
- **API Key**: Configured via `GEMINI_API_KEY` environment variable
- **Environment**: `USE_GEMINI=true` by default (set to `false` to use Llama fallback)
- **Fallback**: Local Llama (Phi-3-mini-4k-instruct-q4) available when `USE_GEMINI=false`
- **Language Support**: Native Thai language prompts, better mixed-language handling
- **Status**: Active default (updated 2026-08-11 to make Gemini the default)

### Legacy Local Model
- **Model**: Phi-3-mini-4k-instruct-q4 (2.3GB)
- **GPU**: NVIDIA GTX 1650 (4GB VRAM)
- **API Endpoint**: `http://tony-omen.local:8001/v1/chat/completions`
- **Context Window**: 4K tokens
- **Status**: Available as fallback, not actively used in production

### Alternative Model
- **Model**: thai-legal-gemma-4b-cpt.Q4_K_M.gguf (5.0GB)
- **Location**: `/data/gguf/` (available but offline)
- **Specialization**: Thai legal content, better Thai language understanding
- **Status**: **Offline as of 2026-08-06** - Removed from docker-compose alias to save GPU resources
- **Reason**: GPU memory constraints (5GB model vs 4GB available VRAM)

### Model Switching Constraints
- Thai legal model (5GB) exceeds available GPU memory (4GB)
- Removed from docker-compose alias (2026-08-06) to prevent load attempts
- Phi-3-mini (2.3GB) now the only active model
- Context size exceeded errors indicate Phi-3 overload under current request volume
- Thai legal model can be re-enabled by adding back to docker-compose alias if GPU upgraded

### Model Management
```bash
# Check loaded models
curl http://tony-omen.local:8001/v1/models | jq .

# Check GPU memory usage
docker exec thai-legal-inference nvidia-smi

# Check Llama server health
curl http://tony-omen.local:8001/health
```

