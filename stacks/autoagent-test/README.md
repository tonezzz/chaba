# AutoAgent Test Stack

Minimal test stack for evaluating AutoAgent capabilities on pc1.

## Quick Start

1. **Configure API Keys**
   ```bash
   cp .env.example .env
   # Edit .env and add at least one LLM API key
   ```

2. **Build and Start**
   ```bash
   docker-compose up -d --build
   ```

3. **Enter Container**
   ```bash
   docker exec -it autoagent-test bash
   ```

4. **Test AutoAgent**
   ```bash
   # Start deep research mode (lightweight)
   auto deep-research
   
   # Or start full AutoAgent with all features
   auto main
   ```

## Configuration

### Environment Variables

- `AUTOAGENT_HTTP_PORT`: Web interface port (default: 8095)
- `AUTOAGENT_MODEL`: LLM model to use (default: claude-3-5-sonnet-20241022)
- `AUTOAGENT_DEBUG`: Enable debug logging (default: false)

### Supported LLM Providers

- OpenAI (`OPENAI_API_KEY`)
- Anthropic Claude (`ANTHROPIC_API_KEY`)
- Google Gemini (`GEMINI_API_KEY`)
- Deepseek (`DEEPSEEK_API_KEY`)
- Groq (`GROQ_API_KEY`)
- xAI Grok (`XAI_API_KEY`)
- Hugging Face (`HUGGINGFACE_API_KEY`)

## Usage Examples

### Deep Research Mode
```bash
# Inside container
auto deep-research
# Follow prompts to enter research query
```

### Full AutoAgent Mode
```bash
# Inside container
auto main
# Choose from: user mode, agent editor, workflow editor
```

### Custom Model
```bash
COMPLETION_MODEL=gpt-4o auto deep-research
```

## Testing Checklist

- [ ] Container builds successfully
- [ ] API keys are properly configured
- [ ] Deep research mode starts
- [ ] LLM responds to queries
- [ ] File upload functionality works
- [ ] Browser automation functions
- [ ] Agent creation via natural language
- [ ] Workflow editor functions

### Import / CLI sanity checks

- [ ] `python -c "import autoagent"` succeeds
- [ ] `auto --help` succeeds
- [ ] `auto deep-research --help` succeeds

## Architecture

```
autoagent-test (container)
├── /app          # AutoAgent installation
├── /workspace    # User workspace
├── /entrypoint.sh # Interactive entrypoint
└── /ms-playwright # Browser dependencies
```

## Integration Points

- **Port 8095**: Potential web interface (if implemented)
- **Workspace Volume**: Persistent storage for files
- **Docker Network**: Can connect to other pc1 services

## Troubleshooting

### Common Issues

1. **No API Keys Configured**
   - Ensure at least one LLM API key is set in .env
   - Check key format and permissions

2. **Browser Issues**
   - Playwright browsers are pre-installed
   - Container includes necessary system dependencies

3. **Permission Issues**
   - Workspace directory has 777 permissions
   - All operations run as root in container

### Logs

```bash
# View container logs
docker-compose logs -f autoagent

# Enter container for debugging
docker exec -it autoagent-test bash
```

## Minimal Testing (No External Dependencies)

For fast CI/testing without VPN or API keys:

### Quick Smoke Test

```bash
# Fast container build + basic checks
./test-minimal.sh
```

This tests:
- Container builds and starts
- Python imports (`autoagent`, `constant`, `loop_utils`, `evaluation`)
- CLI availability (`auto --help`)
- Control server health endpoint

### Mocked Unit Tests

```bash
# Run inside container (no API calls)
docker exec autoagent-test python /app/test-mocked.py
```

Tests include:
- GhostRoute ranking algorithm
- Environment config parsing
- Command validation
- Model/provider inference logic
- Control server paths

### Minimal Compose (No VPN/Postgres)

```bash
# Start lightweight version
docker-compose -f docker-compose.minimal.yml up -d --build

# Run mocked tests
docker-compose -f docker-compose.minimal.yml exec autoagent python /app/test-mocked.py

# Cleanup
docker-compose -f docker-compose.minimal.yml down -v
```

### Health Endpoint

```bash
# Full stack
curl http://localhost:8059/api/health

# Minimal stack (different ports)
curl http://localhost:8096/api/health
```

Returns JSON with:
- Import status for all modules
- CLI availability
- API key configuration
- Workspace writable status

## Next Steps

1. Configure API keys and test basic functionality
2. Evaluate deep research capabilities
3. Test agent creation and workflow features
4. Assess integration possibilities with existing pc1 services
5. Consider production deployment requirements

## Resources

- [AutoAgent GitHub](https://github.com/HKUDS/AutoAgent)
- [AutoAgent Paper](https://arxiv.org/abs/2502.05957)
- [AutoAgent Documentation](https://autoagent-ai.github.io/docs)
