# Windsurf MCP Memory server in webtop

## Problem
Windsurf's MCP plugin is configured to launch the Memory server via `npx`, but the runtime environment where Windsurf spawns MCP stdio servers (the webtop environment) does not have `npx` on `$PATH`.

Observed error:
- `failed to create mcp stdio client: failed to start stdio transport: failed to start command: exec: "npx": executable file not found in $PATH`

Webtop entrypoint URL:
- `https://test.idc1.surf-thailand.com/webtop/`

Repo note:
- This repository does not currently define the webtop container/service. The idc1 control panel page notes `/webtop/` is reverse-proxied to `127.0.0.1:3001`.

## Windsurf MCP config snippet
File (outside repo):
- `/config/.codeium/windsurf/mcp_config.json`

Server definition:
```json
{
  "mcpServers": {
    "memory": {
      "args": [
        "-y",
        "@modelcontextprotocol/server-memory"
      ],
      "command": "npx",
      "env": {
        "MEMORY_FILE_PATH": "/workspaces/chaba/data/windsurf/mcp-memory/"
      }
    }
  }
}
```

## Next steps
1. Identify the webtop container image and OS on the host (so we know how to install Node/npm):
   - `docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}' | grep -i -E 'webtop|3001'`
2. Verify whether Node tooling exists inside the webtop container:
   - `docker exec -it <webtop_container> sh -lc 'command -v npx || echo NO_NPX; command -v npm || echo NO_NPM; command -v node || echo NO_NODE; echo "$PATH"'`
3. Fix options:
   - Install Node/npm into the webtop container image (persistent) so `npx` exists.
   - Alternatively, switch the Memory server to use `npm exec --yes @modelcontextprotocol/server-memory` if `npm` exists but `npx` does not.
