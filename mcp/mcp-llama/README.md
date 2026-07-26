# mcp-llama

FastMCP wrapper for the `llama.cpp` OpenAI-compatible HTTP server.

## Quick start

1. Place a `.gguf` model in `data/models/` (relative to the `chaba-omen` worktree).
   The default expected filename is `Llama-3.2-3B-Instruct-Q4_K_M.gguf`.
   You can override it with the `LLAMA_MODEL` environment variable.

2. Start the llama-server container:

   ```bash
   make llama-up
   ```

   To use a different model or layer count (for example, the downloaded `Phi-3-mini` on a 4GB GPU):

   ```bash
   LLAMA_MODEL=Phi-3-mini-4k-instruct-Q4_K_M.gguf \
   LLAMA_N_GPU_LAYERS=0 \
     make llama-up
   ```

3. Check health:

   ```bash
   make llama-status
   # or
   curl http://localhost:8008/health
   ```

4. Install the MCP server (optional venv recommended):

   ```bash
   pip install -r mcp/mcp-llama/requirements.txt
   ```

5. Add to your Windsurf / Cascade MCP config (`~/.config/windsurf/mcp_config.json` or similar):

   ```json
   {
     "mcpServers": {
       "mcp-llama": {
         "command": "python3",
         "args": [
           "/home/tony/CascadeProjects/chaba-omen/mcp/mcp-llama/server.py"
         ],
         "env": {
           "LLAMA_URL": "http://localhost:8008"
         }
       }
     }
   }
   ```

## Environment variables

- `LLAMA_URL` — URL of the llama-server HTTP API (default `http://localhost:8008`).
- `LLAMA_MODEL_DIR` — Directory scanned by the `models()` tool for available `.gguf` files.
  Default resolves to `chaba-omen/data/models`.
- `LLAMA_MODEL` — Filename of the model to load in the Docker service.
  Default: `Llama-3.2-3B-Instruct-Q4_K_M.gguf`.
- `LLAMA_N_GPU_LAYERS` — Number of layers to offload to the GPU (`--n-gpu-layers`).
  Default: `0` (CPU) to avoid OOM on the 4GB GTX 1650; set to `99` to offload all layers if you have enough VRAM.

## Tools

- `chat(prompt, system=None, max_tokens=512, temperature=0.7)` — OpenAI-compatible chat completion.
- `complete(prompt, max_tokens=256, temperature=0.7)` — Raw text completion.
- `tokenize(text)` — Return token IDs for the given text.
- `models()` — List `.gguf` files in the model directory.
- `status()` — Query `/health` on llama-server.

## Useful commands

```bash
make llama-up       # create data/models and start the container
make llama-down     # stop the llama-server container
make llama-logs     # follow logs
make llama-status   # curl /health
```
