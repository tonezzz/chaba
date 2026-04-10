# GhostRoute Discovery

Automated testing and ranking of OpenRouter free models for AutoAgent and other apps.

## Quick Start

### Run Discovery Test

```bash
cd /app
python test-ghostroute.py
```

### Use Discovery in Other Stacks

```bash
# Load recommended config into environment
export $(cat /workspace/discovery/ghostroute/latest/recommended_config.json | jq -r '.autoagent_env | to_entries[] | "\(.key)=\(.value)"')
```

## Discovery Files

| File | Purpose |
|------|---------|
| `latest/models_ranked.json` | All free models ranked by GhostRoute algorithm |
| `latest/test_results.json` | Actual test results (latency, success/failure) |
| `latest/recommended_config.json` | Best config for AutoAgent |

## GhostRoute Algorithm

Models are scored (0-1) using:
- **Context Length** (40%) - Larger context = bigger tasks
- **Capabilities** (30%) - Tools, vision, structured output
- **Recency** (20%) - Newer models perform better
- **Provider Trust** (10%) - Anthropic > Google/OpenAI > Meta > others

## Fallback Chain

The recommended config includes a fallback chain:
1. `openrouter/free` - Smart capability-aware router
2. Top ranked free models (tested)
3. Additional free models for redundancy

## Integration

### For AutoAgent (this stack)
Discovery is automatically used via volume mount at `/workspace/discovery`

### For Other MCP Tools
```python
import json

with open("/workspace/discovery/ghostroute/latest/recommended_config.json") as f:
    config = json.load(f)
    
model = config["primary_model"]
fallbacks = config["fallback_chain"]
```

### For idc1-assistance / Other Stacks
Copy discovery or mount as volume:
```yaml
volumes:
  - /path/to/discovery/ghostroute:/discovery/ghostroute:ro
```

## Updating Discovery

Run test periodically to keep rankings fresh:
```bash
# Manual
python test-ghostroute.py

# Or via scheduled job (cron, etc.)
```

## Top Models (Example)

Based on typical rankings:
1. `anthropic/claude-3.5-sonnet:free` - Best overall
2. `google/gemini-2.0-flash-exp:free` - Fast, good context
3. `meta-llama/llama-3.3-70b-instruct:free` - Solid open model
4. `microsoft/phi-4:free` - Good smaller model
