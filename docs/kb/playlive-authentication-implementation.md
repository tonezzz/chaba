---
category: operations
---

# Implementation

### Daemon Changes (`playlived.mjs`)

Added HTTP basic authentication support using Playwright's context-level credentials:

```javascript
// Session object now includes httpCredentials field
const session = { id, type, target, cdpUrl, browser, context, page, createdAt: Date.now(), reuse_context, attached, httpCredentials: null };

// set_auth action to configure credentials
case 'set_auth': {
  const { username, password } = body || {};
  if (!username || typeof username !== 'string') throw new Error('username required');
  if (!password || typeof password !== 'string') throw new Error('password required');
  s.httpCredentials = { username, password };
  await s.context.setHTTPCredentials({ username, password });
  return { set: true, username };
}

// clear_auth action to remove credentials
case 'clear_auth': {
  s.httpCredentials = null;
  await s.context.setHTTPCredentials(null);
  return { cleared: true };
}
```

### MCP Client Changes (`playlive-server.py`)

Added new tools for credential management:

```python
@mcp.tool()
def playlive_set_auth(session_id: str, username: str, password: str) -> str:
    """Set basic authentication credentials for the session. These credentials will be used for all subsequent navigate requests."""
    return json.dumps(_request("POST", f"/sessions/{session_id}/set_auth", {"username": username, "password": password}), indent=2)

@mcp.tool()
def playlive_clear_auth(session_id: str) -> str:
    """Clear basic authentication credentials from the session."""
    return json.dumps(_request("POST", f"/sessions/{session_id}/clear_auth", {}), indent=2)
```

### SSOT Documentation

Updated `docs/ssot/apps/ssot.apps.playlive.yml` with authentication section:

```yaml
- title: Authentication
  icon: 🔐
  layout: list
  items:
    - label: Basic auth support
      text: PlayLive sessions can be configured with basic authentication credentials for accessing protected pages.
    - label: Credential configuration
      text: Credentials passed via playlived configuration or session creation parameters (username/password).
    - label: Use case
      text: Enables verification of Caddy-protected pages like /apps/yomi/* which require basic auth.
```

## Usage

### Basic Workflow

1. Create a PlayLive session
2. Set authentication credentials
3. Navigate to protected page
4. Clear credentials (optional)

### Example Usage

```bash
# Create session
curl -X POST http://tony-dell.local:9230/sessions -H "Content-Type: application/json" -d '{"type":"chrome-live","target":"remote"}'

# Set credentials
curl -X POST http://tony-dell.local:9230/sessions/{session_id}/set_auth -H "Content-Type: application/json" -d '{"username":"yomi","password":"Love2521**"}'

# Navigate to protected page
curl -X POST http://tony-dell.local:9230/sessions/{session_id}/navigate -H "Content-Type: application/json" -d '{"url":"http://tony-omen.local:8080/apps/yomi/daily2/index.html?chat=cc8589a45e890e38942825d3c13ec3439"}'

# Clear credentials
curl -X POST http://tony-dell.local:9230/sessions/{session_id}/clear_auth -H "Content-Type: application/json" -d '{}'
```

### MCP Tool Usage

```python
# Set authentication
mcp_call_tool("playlive.tony-dell", "playlive_set_auth", {
  "session_id": "session_id",
  "username": "yomi",
  "password": "Love2521**"
})

# Navigate to protected page
mcp_call_tool("playlive.tony-dell", "playlive_navigate", {
  "session_id": "session_id",
  "url": "http://tony-omen.local:8080/apps/yomi/"
})
```

## Technical Details

### Credential Storage

- Credentials are stored in session object as `httpCredentials` field
- Applied at Playwright context level using `context.setHTTPCredentials()`
- Persist for all subsequent requests in the session
- Must be explicitly cleared with `clear_auth` action

### Playwright Implementation

Uses Playwright's built-in HTTP authentication support:
- Credentials set at context level apply to all pages in that context
- Automatically handles basic auth challenges
- Supports both HTTP and HTTPS protocols
- Compatible with Caddy's `basicauth` directive

### Security Considerations

- Credentials are stored in memory only (session-based)
- No persistent storage of credentials
- Daemon is unauthenticated on LAN (existing security model)
- Auth is for target page access only, not daemon security
- Do not expose playlived to untrusted networks

