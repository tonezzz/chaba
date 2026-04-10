# GhostRoute Testing Guide

## What is GhostRoute?

[GhostRoute](https://github.com/kittimasak/GhostRoute) is a free AI router for OpenClaw that:
- Ranks OpenRouter free models by quality
- Builds resilient fallback chains (survives 429/503 errors)
- Auto-rotates primary models for maximum uptime

## Testing Approach

Since GhostRoute is designed for OpenClaw but we use AutoAgent + LiteLLM, we implement our own **compatible ranking algorithm** that produces similar results.

### Discovery Algorithm (GhostRoute-compatible)

```
Score = (Context Length × 0.40) + 
        (Capabilities × 0.30) + 
        (Recency × 0.20) + 
        (Provider Trust × 0.10)
```

**Factors:**
- **Context Length** (40%): Larger context windows handle bigger tasks
- **Capabilities** (30%): Tool use, vision, structured output support
- **Recency** (20%): Newer models generally perform better
- **Provider Trust** (10%): Anthropic > Google/OpenAI > Meta > others

## How to Test

### Quick Test (inside container)

```bash
# Enter container
docker exec -it autoagent-test bash

# Run discovery test
cd /app
python test-ghostroute.py

# Query results
python mcp-query.py best        # Best model
python mcp-query.py fallbacks   # Fallback chain
python mcp-query.py config      # Full config
python mcp-query.py list 20     # Top 20 ranked models
```

### Full Workflow (from host)

```bash
cd stacks/autoagent-test
./test-ghostroute-full.sh
```

## Discovery Output

Files saved to `discovery/ghostroute/latest/`:

| File | Contents |
|------|----------|
| `models_ranked.json` | All free models with GhostRoute scores |
| `test_results.json` | Actual latency/success tests |
| `recommended_config.json` | Best config for AutoAgent |

## Using Discovery in Other Apps

### Option 1: Mount as Volume

```yaml
# In other stack's docker-compose.yml
services:
  myapp:
    volumes:
      - autoagent-discovery:/discovery/ghostroute:ro

volumes:
  autoagent-discovery:
    external: true
    name: autoagent-test_autoagent-workspace
```

### Option 2: Copy Config

```bash
# Load env vars from discovery
docker exec autoagent-test cat /workspace/discovery/ghostroute/latest/recommended_config.json | \
  jq -r '.autoagent_env | to_entries[] | "\(.key)=\(.value)"' > .env.ghostroute
```

### Option 3: MCP Tool Query

```python
import subprocess
import json

result = subprocess.run([
    "docker", "exec", "autoagent-test",
    "python", "/app/mcp-query.py", "config"
], capture_output=True, text=True)

config = json.loads(result.stdout)
model = config["primary_model"]
fallbacks = config["fallback_chain"]
```

## Typical Top Models

Based on GhostRoute ranking:

1. `anthropic/claude-3.5-sonnet:free` - Best overall (200k context, reliable)
2. `google/gemini-2.0-flash-exp:free` - Fast, multimodal, 1M context
3. `meta-llama/llama-3.3-70b-instruct:free` - Solid open model
4. `deepseek/deepseek-chat:free` - Good reasoning, 64k context
5. `microsoft/phi-4:free` - Efficient smaller model

## Fallback Chain Strategy

```
Primary: anthropic/claude-3.5-sonnet:free
Fallback 1: openrouter/free          (smart router)
Fallback 2: google/gemini-2.0-flash-exp:free
Fallback 3: meta-llama/llama-3.3-70b-instruct:free
Fallback 4: deepseek/deepseek-chat:free
Fallback 5: ... (more free models)
```

## Integration with AutoAgent

The discovery automatically updates `AUTOAGENT_MODEL` in the `.env` file.

To use in AutoAgent:
```bash
# Load GhostRoute config
docker exec autoagent-test bash -c "source /app/load-config.sh && env | grep AUTOAGENT"

# Or set directly
docker exec autoagent-test auto main --model anthropic/claude-3.5-sonnet:free
```

## Maintenance

Run discovery test periodically to keep rankings fresh:
- Models change frequently on OpenRouter
- Free tier availability varies
- New models added regularly

```bash
# Schedule weekly update
crontab -e
# Add: 0 0 * * 0 cd /path/to/chaba/stacks/autoagent-test && ./test-ghostroute-full.sh
```
