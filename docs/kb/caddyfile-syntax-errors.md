---
category: operations
---

# Caddyfile Syntax Errors

## What it is

Caddyfile syntax errors that prevent the Caddy web server from starting, causing connection failures for all web services.
## Context/Background

Created 2026-08-04 as part of Chaba infrastructure documentation.


## Context

Caddy configuration files must follow specific syntax rules. When these rules are violated, Caddy fails to start and all web services become unavailable.

## Common Error: Global Request Matchers

### Error Message
```
Error: adapting config using caddyfile: request matchers may not be defined globally, they must be in a site block; found @matcher_name, at /etc/caddy/Caddyfile:line_number
```

### Root Cause

Request matchers (like `@noslash`, `@api`, etc.) must be defined within site blocks (e.g., `:8080 { ... }`), not globally outside of any site block.

### Example of Incorrect Configuration

```caddyfile
:8080 {
    # ... configuration ...
}

@global_matcher path /apps/something
redir @global_matcher /apps/something/ 308
```

### Correct Configuration

```caddyfile
:8080 {
    @global_matcher path /apps/something
    redir @global_matcher /apps/something/ 308
    
    # ... rest of configuration ...
}
```

## Specific Case: Duplicate Tradecanvas Matcher

### Issue
Duplicate `@tradecanvas_ui_noslash` matcher defined globally at line 405 in Caddyfile, causing Caddy startup failure.

### Error
```
Error: adapting config using caddyfile: request matchers may not be defined globally, they must be in a site block; found @tradecanvas_ui_noslash, at /etc/caddy/Caddyfile:405
```

### Resolution
Removed the duplicate global matcher definition. The correct definition already existed inside the `:8080` site block at line 371.

### Before Fix
```caddyfile
:8080 {
    # ... configuration ...
    @tradecanvas_ui_noslash path /apps/trade/tradecanvas-ui
    redir @tradecanvas_ui_noslash /apps/trade/tradecanvas-ui/ 308
    # ... rest of configuration ...
}

# INCORRECT: Duplicate global matcher
@tradecanvas_ui_noslash path /apps/trade/tradecanvas-ui
redir @tradecanvas_ui_noslash /apps/trade/tradecanvas-ui/ 308
```

### After Fix
```caddyfile
:8080 {
    # ... configuration ...
    @tradecanvas_ui_noslash path /apps/trade/tradecanvas-ui
    redir @tradecanvas_ui_noslash /apps/trade/tradecanvas-ui/ 308
    # ... rest of configuration ...
}
```

## Troubleshooting Steps

### 1. Check Caddy Logs
```bash
docker logs web --tail 20
```

### 2. Validate Caddyfile Syntax
```bash
docker compose config web
```

### 3. Test Configuration
```bash
docker compose run --rm web caddy validate --config /etc/caddy/Caddyfile
```

### 4. Restart Web Stack
```bash
cd /home/tony/CascadeProjects/chaba/stacks/web
docker compose restart web
```

### 5. Verify Web Stack is Running
```bash
docker compose ps web
curl -s http://localhost:8080/apps/health-check/
```

## Prevention

### Code Review Checklist
- Ensure all request matchers are defined within site blocks
- Check for duplicate matcher definitions
- Verify all matchers are used within their site block
- Use consistent indentation to identify site block boundaries

### Site Block Structure
```caddyfile
:8080 {
    # All matchers must be defined here
    @matcher_name path /path
    redir @matcher_name /path/ 308
    
    handle_path /path/* {
        # Handler configuration
    }
}
```

## Common Caddyfile Patterns

### Path Redirects
```caddyfile
@noslash path /apps/example
redir @noslash /apps/example/ 308
```

### API Handlers
```caddyfile
handle /api/example/* {
    reverse_proxy backend:8080
}
```

### Static File Serving
```caddyfile
handle_path /apps/example/* {
    root * /srv/public/apps/example
    file_server
}
```

## Related Documentation

- `chaba/stacks/web/Caddyfile` - Main Caddy configuration
- `chaba/stacks/web/docker-compose.yml` - Docker compose configuration
- [Caddyfile Documentation](https://caddyserver.com/docs/caddyfile) - Official Caddyfile reference

## Tags

- **docker**: docker
- **containers**: containers
- **containerization**: containerization
- **api**: api
- **rest**: rest
- **http**: http
- **web**: web
- **documentation**: documentation
- **kb**: kb
- **knowledge-base**: knowledge-base
- **2026**: 2026
