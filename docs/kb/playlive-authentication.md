# PlayLive Basic Authentication

## What it is

PlayLive browser automation daemon extended with basic authentication support to enable verification of Caddy-protected pages like Yomi web interface.

## Context

PlayLive is a remote browser-control facility that lets multiple AI clients drive Chrome/Playwright sessions through a shared daemon. Previously, it could not access pages protected by HTTP basic authentication, limiting verification capabilities for protected services like Yomi.

## Implementation

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

## Known Protected Services

### Yomi Web Interface
- **URL**: `http://tony-omen.local:8080/apps/yomi/*`
- **Credentials**: yomi/Love2521**
- **Protection**: Caddy basic auth with bcrypt hash
- **Config**: `chaba/stacks/web/.env` contains `YOMI_PASSWORD_HASH`

### Caddy Configuration

```caddyfile
handle_path /apps/yomi/* {
    root * /srv/public/apps/yomi
    basicauth {
        yomi {env.YOMI_PASSWORD_HASH}
    }
    file_server
}
```

## Troubleshooting

### Auth Not Working
- Verify credentials are correct
- Check that `set_auth` was called before navigation
- Ensure target page actually uses basic auth
- Check browser console for auth errors

### Connection Refused Errors
- Verify web stack is running: `docker compose ps`
- Check Caddyfile syntax: `docker logs web`
- Ensure target hostname is accessible from PlayLive host

### Caddyfile Syntax Errors
- Request matchers must be defined within site blocks, not globally
- Example error: `request matchers may not be defined globally, they must be in a site block`
- Fix: Move matchers inside `:8080 { ... }` or `:8081 { ... }` blocks

## Related Documentation

- `docs/ssot/apps/ssot.apps.playlive.yml` - PlayLive SSOT documentation
- `chaba/stacks/web/Caddyfile` - Caddy configuration with basic auth
- `chaba/stacks/web/.env` - Environment variables including password hashes
- `docs/kb/yomi.md` - Yomi web application documentation

## Tags

playlive, authentication, basic-auth, browser-automation, caddy, yomi, security