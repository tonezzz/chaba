# Google Drive MCP Migration Guide

## Overview
Jarvis now supports Google Sheets operations via the `google-drive-mcp` server instead of the legacy Sheets API client.

## Architecture
- **Sheets backend**: `google-drive-mcp` (service account, MCP-over-HTTP).
- **Adapter**: `jarvis/integrations/sheets.py`.

## Services
- `google-drive-mcp` runs in the stack at `http://google-drive-mcp:8032` (internal only).
- Uses a **service account** JSON key mounted at `/app/creds/service-account.json`.

## Environment variables
```bash
# MCP client config
GOOGLE_DRIVE_MCP_BASE_URL=http://google-drive-mcp:8032
```

## Stack wiring
- Service added to `stacks/idc1-assistance-core/docker-compose.yml`.
- Volume `google-drive-mcp-creds` holds the service account JSON.
- Healthcheck hits `/health` on the MCP server.

## Adapter functions
All existing Sheets functions are now available via `jarvis.integrations.sheets`:
- `get_values`
- `append_rows`
- `update_values`
- `upsert_kv`
- `append_log`
- `read_memo_rows`
- `write_memo_rows`
- `test_connectivity`

## Migration steps
1. **Create a Google Service Account** and grant it access to your Drive/Sheets.
2. **Store the service account JSON** in Portainer as a secret/volume.
3. **Deploy the updated stack** with `google-drive-mcp` added.
4. **Test connectivity** via the adapter (`test_connectivity`).
5. **Verify** logs, system KV, and memos work via Drive MCP.

## Cleanup (post-migration)
- Remove `jarvis/integrations/sheets_legacy.py`.
- Remove `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN` from Portainer env.
- Remove `google-api-python-client` and `google-auth-oauthlib` from requirements.
- Update documentation to reference Drive MCP.

## Troubleshooting
- **403/404 from MCP**: Ensure the service account has access to the target sheets.
- **Container can't reach MCP**: Verify internal DNS (`google-drive-mcp:8032`) and network.
- **Auth errors**: Confirm the service account JSON is mounted and readable.

## Notes
- The MCP adapter mirrors the legacy Sheets client signatures to minimize code changes.
- All operations are synchronous; if you need async, wrap the calls.
