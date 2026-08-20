---
category: operations
---

# Known Protected Services

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

