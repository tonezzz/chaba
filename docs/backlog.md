# Backlog

## MCP

- Samsung SmartThings MCP integration (evaluate and potentially adopt)
  - Repo: https://github.com/PaulaAdelKamal/samsung_smartthings-mcp
  - Notes: Improve TV-device detection, reuse aiohttp session + timeouts, better SmartThings error reporting, fix doc/filename typos (test_smarthings.py), clarify PAT rotation guidance, handle .env/.gitignore

- Investigate `mcp-voyant` and `mcp-travel` (deferred until core services stabilize)
  - Goal: identify where these servers are registered (pc1 1mcp config), where they run (transport/url), and their build/source-of-truth.
  - Note: this repo does not currently contain `mcp-voyant`, `mcp-travel`, or a `voyant/` folder; the only reference seen was an `idc1-stack/1mcp-agent/Dockerfile` `COPY voyant/1mcp-agent-src ...` line, suggesting an external build context.
