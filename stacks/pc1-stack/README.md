# pc1-stack

## Overview
This stack provides a VPN-only chat UI (OpenChat UI) backed by an OpenAI-compatible gateway service. The gateway uses Glama as the model backend and exposes MCP tools from `1mcp-agent` (including `mcp-task`, `mcp-devops`, and `docker`) for tool calling.

## Services (key)
- `openchat-ui` (Next.js): user-facing chat UI
- `mcp-openai-gateway` (FastAPI): OpenAI-compatible `/v1/*` endpoints used by OpenChat UI
- `1mcp-agent`: MCP tool aggregator (HTTP Streamable)
- `mcp-task`: task/run service (exposed as tools via 1mcp)
- `mcp-devops`: devops workflows (tools via 1mcp)
- `mcp-rag`: text+image RAG (Ollama embeddings + Qdrant)

## Start
From `stacks/pc1-stack/`:

```powershell
# Copy env template and set secrets
copy .env.example .env

# Start the stack
Docker compose --profile mcp-suite up -d --build
```

## URLs
### Direct ports
- OpenChat UI: `http://pc1.vpn:3170`
- 1mcp-agent: `http://1mcp.pc1.vpn:3051/health`
- OpenAI gateway: `http://pc1.vpn:8181/health`
- mcp-rag (health): `http://pc1.vpn:8055/health`
- mcp-rag (manifest): `http://pc1.vpn:8055/.well-known/mcp.json`
- mcp-rag (mcp): `http://pc1.vpn:8055/mcp`
- mcp-doc-archiver (health): `http://pc1.vpn:8066/health`
- mcp-doc-archiver (UI): `http://pc1.vpn:8066/docs/`

### VPN HTTPS (stack Caddy)
pc1-stack runs a Caddy container using `tls internal` on host port `3443`.

- OpenChat UI: `https://pc1.vpn:3443/chat/`
- OpenAI gateway (health): `https://pc1.vpn:3443/openai/health`
- OpenAI gateway (models): `https://pc1.vpn:3443/openai/v1/models`
- 1mcp-agent: `https://pc1.vpn:3443/1mcp/health`
- mcp-rag (health): `https://rag.pc1.vpn/health`
- mcp-rag (manifest): `https://rag.pc1.vpn/.well-known/mcp.json`
- mcp-rag (mcp): `https://rag.pc1.vpn/mcp`
- Doc Archiver (UI): `https://pc1.vpn:3443/docs/`
- Doc Archiver (health): `https://pc1.vpn:3443/docs/health`
- Doc Archiver (API): `https://pc1.vpn:3443/docs/api/*`

## Doc Archiver (runbook)
### What it does
- Upload documents (PDF/image/text)
- Extract text (PDF text + OCR fallback via tesseract)
- Chunk and store metadata in SQLite
- Auto-index chunks into `mcp-rag` (Qdrant)
- Chat with citations using `mcp-openai-gateway`

### Key endpoints
- UI: `GET /docs/`
- List docs: `GET /docs/api/docs`
- Ingest (auto-indexes): `POST /docs/api/ingest` (multipart `file`, `doc_group`, `labels`, `doc_type`)
- Manual index: `POST /docs/api/docs/{doc_id}/index`
- Chat: `POST /docs/api/chat`
- Extract structured fields: `POST /docs/api/extract`

### Data storage
- SQLite DB: `${DOC_ARCHIVER_DB_PATH}` (default: `/data/sqlite/doc-archiver.sqlite`)
- Artifacts dir: `${DOC_ARCHIVER_ARTIFACT_DIR}` (default: `/data/artifacts`)

### Environment variables
- `MCP_DOC_ARCHIVER_PORT` (compose host port, default `8066`)
- `DOC_ARCHIVER_DATA_DIR` (default `/data`)
- `DOC_ARCHIVER_DB_PATH` (default `${DOC_ARCHIVER_DATA_DIR}/sqlite/doc-archiver.sqlite`)
- `DOC_ARCHIVER_ARTIFACT_DIR` (default `${DOC_ARCHIVER_DATA_DIR}/artifacts`)
- `DOC_ARCHIVER_MCP_RAG_URL` (default `http://mcp-rag:8055`)
- `DOC_ARCHIVER_OPENAI_BASE_URL` (default `http://mcp-openai-gateway:8181`)
- `DOC_ARCHIVER_OPENAI_MODEL` (default `glama-default`)
- `DOC_ARCHIVER_TIMEOUT_SECONDS` (default `60`)

## Notes
- `stacks/pc1-stack/.env` is local-only (gitignored). Do not commit real API keys.
- `OPENAI_GATEWAY_DEBUG=1` enables `/debug/*` endpoints on the gateway for troubleshooting.
