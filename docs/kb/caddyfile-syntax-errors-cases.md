---
category: operations
---

# Common Error: Global Request Matchers

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

