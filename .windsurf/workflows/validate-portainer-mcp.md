---
description: Validate Portainer MCP connectivity + basic operations
---

# Goal
Confirm Portainer MCP is reachable and can list stacks; optionally confirm write operations are enabled when intended.

# Read checks
- `listLocalStacks` works.
- Tool calls return without connection resets.

# Write checks (only if you intend write access)
- Confirm the environment is configured with `PORTAINER_READ_ONLY=0` (or equivalent).
- Use a non-destructive write operation only when needed.

# Suggested validation sequence
1. `listLocalStacks`
2. Identify stack by name (e.g. `idc1-assistance`).
3. If write is enabled and you are doing a real deploy:
   - Use `updateLocalStack` for compose/env changes.
   - Use stop/start only for bounce.

# Common failures
- Missing/empty server URL or token passed to portainer-mcp.
- Read-only mode accidentally enabled.
- Port conflicts preventing MCP endpoint exposure.
