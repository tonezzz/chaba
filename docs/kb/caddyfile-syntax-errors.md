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

## See also

- [Caddyfile Syntax Errors Cases](caddyfile-syntax-errors-cases.md)
