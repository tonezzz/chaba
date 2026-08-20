---
category: operations
---

# Current Implementation

### Raceman Project
- **Playwright Version**: 1.61.1
- **Purpose**: E2E testing of raceman application
- **Target**: localhost:8083 (raceman container)
- **Test Files**: e2e/track3.spec.js, e2e/imagen2.spec.js, e2e/reefriders.spec.js

### PlayLive Daemon
- **Hosts**:
  - `tony-omen.local:9231` — consolidated session daemon
  - `tony-dell.local:9230` — UI verification daemon for offloading browser work from `tony-omen`
- **Chrome CDP on tony-dell**: `http://127.0.0.1:9222`
- **Purpose**: AI-driven browser automation and UI verification
- **MCP Servers**: `playlive.local` (tony-omen), `playlive.tony-dell` (tony-dell, disabled by default in `mcp_config.json`)

## Session Types in PlayLive

1. **chrome-live**: CDP-attached to existing Chrome
2. **playwright-chrome**: Playwright attached to CDP Chrome  
3. **playwright-headless**: Local headless Playwright browser

## Technical Implementation

### PlayLive Daemon (playlived.mjs)
```javascript
import { chromium } from 'playwright';

// Session management
const sessions = new Map();

// Uses Playwright for browser control
const browser = await chromium.connect(cdpUrl);
const context = await browser.newContext();
const page = await context.newPage();
```

### MCP Client (playlive-server.py)
```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mcp-playlive")

# Exposes HTTP API as MCP tools
@mcp.tool()
def playlive_navigate(session_id: str, url: str) -> str:
    return json.dumps(_request("POST", f"/sessions/{session_id}/navigate", {"url": url}))
```

## Independence of Installations

The raceman project's Playwright installation is independent of the PlayLive daemon:
- **Separate installations**: Each has its own Playwright browser cache
- **Different purposes**: Raceman for E2E testing, PlayLive for AI automation
- **No direct dependency**: Changes to one don't affect the other
- **Resource isolation**: Separate browser caches and configurations

## Operational Considerations

### Session Management

PlayLive requires proper session management for effective testing:
- Sessions persist across operations and must be explicitly cleaned up
- Multiple AI agents can share sessions, requiring coordination
- Session state must be managed to prevent conflicts
- Use session IDs to track and manage individual sessions

### Playwright Reinstallation

After system updates or PlayLive daemon updates, Playwright may need reinstallation:
```bash
# Reinstall Playwright browsers
npx playwright install

# Or reinstall with dependencies
npx playwright install --with-deps
```

**Symptoms**:
- PlayLive fails to start browser sessions
- CDP connection errors
- Browser crashes on session creation

**Causes**:
- System updates affecting Playwright binaries
- Playwright version mismatches
- Missing browser dependencies after system updates

### Testing Effectiveness

PlayLive is effective for testing web applications when:
- Proper session management is implemented
- Sessions are cleaned up after testing
- Playwright binaries are up-to-date
- Network connectivity to target applications is verified

## Multi-host PlayLive Deployment

PlayLive can run on both `tony-omen` and `tony-dell` to distribute browser-automation load:

- **tony-omen** (`tony-omen.local:9231`) — consolidated session daemon for general use
- **tony-dell** (`tony-dell.local:9230`) — UI verification daemon; Chrome CDP on `127.0.0.1:9222`

To use `tony-dell` for UI verification:

1. Start `playlived` on `tony-dell` with a new session:
   ```bash
   cd /home/tony/.local/playlive
   setsid -f sh -c 'exec node playlived.mjs > playlived.log 2>&1'
   ```
2. Create a session with `remote_url` set to the local Chrome CDP:
   `http://127.0.0.1:9222` (the daemon default is `9223`, so pass the override explicitly)

## Playwright Version Pinning

The PlayLive browser cache on each host must match the installed `playwright` package. To prevent package/browser binary mismatches, both `tony-omen` and `tony-dell` are pinned to the exact Playwright version:

- `/home/tony/.local/playlive/package.json`: `"playwright": "1.62.0"`
- If Playwright is ever bumped, reinstall browser binaries with: `npx playwright install chromium`

