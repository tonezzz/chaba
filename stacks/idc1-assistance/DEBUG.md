# idc1-assistance debug compose

This directory includes debug-only compose files for running isolated services on non-conflicting ports.

Rules:

- These files are for local/operator testing.
- Do not commit secrets to git. Use `./.env.local` (already gitignored).

## Debug MCP bundle

Start MCP bundle on port `4051`:

- `docker compose -f stacks/idc1-assistance/docker-compose.debug-mcp-bundle.yml up -d`

Verify:

- `curl -sS http://127.0.0.1:4051/ | head`

## Debug Jarvis backend (uses debug MCP)

Start Jarvis backend on port `48018`:

- `docker compose -f stacks/idc1-assistance/docker-compose.debug-jarvis-backend.yml up -d`

It will call MCP at `http://host.docker.internal:4051` by default.

Verify:

- `curl -fsS http://127.0.0.1:48018/health`

Recommended sanity checks:

- `curl -sS http://127.0.0.1:48018/jarvis/debug/memo | jq .`
- `curl -sS -X POST http://127.0.0.1:48018/jarvis/memo/header/normalize | jq .`

Notes:

- If the backend reports missing Sheets auth, ensure the MCP bundle has a valid token file at the configured path.
- These debug containers are intentionally isolated from the Portainer-managed `idc1-assistance` stack.
