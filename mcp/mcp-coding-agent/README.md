# mcp-coding-agent

MCP service that uses an LLM to **analyze**, **fix**, and **review** source code.

## Tools

| Tool | Description |
|------|-------------|
| `analyze_code` | Analyze a code snippet for bugs, security issues, performance problems, and style improvements. Returns severity-ranked findings and an overall quality score. |
| `fix_bugs` | Fix bugs in a code snippet. Accepts an optional error message and bug description. Returns corrected code, a diff-style change list, and an explanation. |
| `review_code` | Thorough code review. Returns a verdict (`approve` / `approve_with_suggestions` / `request_changes`), line-level comments, positives, and an overall score. |

## Quick start

```bash
cp .env.example .env
# Edit .env: set MCP_CODING_AGENT_LLM_BASE_URL, MCP_CODING_AGENT_LLM_API_KEY, MCP_CODING_AGENT_LLM_MODEL
npm install
npm start
```

Server listens on `http://127.0.0.1:8350` by default.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_CODING_AGENT_PORT` | `8350` | HTTP port |
| `MCP_CODING_AGENT_HOST` | `127.0.0.1` | Bind address |
| `MCP_CODING_AGENT_LLM_BASE_URL` | – | OpenAI-compatible base URL (falls back to `GLAMA_API_URL`) |
| `MCP_CODING_AGENT_LLM_API_KEY` | – | API key (falls back to `GLAMA_API_KEY`) |
| `MCP_CODING_AGENT_LLM_MODEL` | – | Model name (falls back to `GLAMA_MODEL`) |
| `MCP_CODING_AGENT_LLM_TEMPERATURE` | `0` | LLM temperature |
| `MCP_CODING_AGENT_JSON_LIMIT` | `4mb` | Express body size limit |
| `MCP_CODING_AGENT_SSE_HEARTBEAT_MS` | `15000` | SSE keep-alive interval (ms) |

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/.well-known/mcp.json` | MCP metadata |
| `POST` | `/mcp` | MCP JSON-RPC (stateful session) |
| `GET` | `/sse` | SSE transport endpoint |
| `POST` | `/messages?session_id=…` | SSE message submission |
| `POST` | `/invoke` | Lightweight direct tool call |

### `/invoke` example

```bash
curl -s http://127.0.0.1:8350/invoke \
  -H 'Content-Type: application/json' \
  -d '{
    "tool": "analyze_code",
    "args": {
      "code": "function add(a,b){ return a - b; }",
      "language": "javascript"
    }
  }'
```

### `/mcp` JSON-RPC example

```bash
# 1. Initialize session
SESSION=$(curl -si http://127.0.0.1:8350/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","clientInfo":{"name":"test"}}}' \
  | grep -i 'mcp-session-id' | awk '{print $2}' | tr -d '\r')

# 2. Mark initialized
curl -s http://127.0.0.1:8350/mcp \
  -H 'Content-Type: application/json' \
  -H "mcp-session-id: $SESSION" \
  -d '{"jsonrpc":"2.0","id":null,"method":"notifications/initialized"}'

# 3. Call a tool
curl -s http://127.0.0.1:8350/mcp \
  -H 'Content-Type: application/json' \
  -H "mcp-session-id: $SESSION" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"fix_bugs","arguments":{"code":"def greet(name):\n  print(\"Hello \" + nam)","language":"python","error_message":"NameError: name '\''nam'\'' is not defined"}}}'
```

## Docker

```bash
docker build -t mcp-coding-agent .
docker run --rm -p 8350:8350 \
  -e MCP_CODING_AGENT_LLM_BASE_URL=https://api.openai.com \
  -e MCP_CODING_AGENT_LLM_API_KEY=sk-... \
  -e MCP_CODING_AGENT_LLM_MODEL=gpt-4o-mini \
  mcp-coding-agent
```
