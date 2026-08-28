---
category: operations
---

# Caddy Direct IP Routing for Docker Containers

## Context

When routing to Docker containers in Caddy, there are two main approaches:

1. **Container name routing**: Use Docker container names (e.g., `reverse_proxy mddb-panel:3002`)
2. **Direct IP routing**: Use container IP addresses (e.g., `reverse_proxy 172.19.0.6:3000`)

## Implementation

**Current MDDB Panel Routing** (Caddyfile):
```caddy
# MDDB Panel
handle_path /apps/mddb/* {
	reverse_proxy 172.19.0.6:3000
	encode gzip
}
```

**Container Details**:
- Container: `mddb-panel`
- Image: `tradik/mddb:panel-latest`
- Container IP: `172.19.0.6`
- Internal Port: `3000`
- Host Port: `3002`

## When to Use Direct IP Routing

**Use direct IP routing when**:
- Container name resolution is unreliable or inconsistent
- Need to bypass Docker's internal DNS for specific routing scenarios
- Container IP is static and predictable (network-scoped or fixed IP)
- Troubleshooting routing issues with container names

**Use container name routing when**:
- Standard Docker networking with dynamic IPs
- Containers may be recreated with different IPs
- Want automatic service discovery
- Following standard Docker networking patterns

## Finding Container IPs

```bash
# Get container IP address
docker inspect <container-name> | grep -A 5 "IPAddress"

# Example for mddb-panel
docker inspect mddb-panel | grep -A 5 "IPAddress"
# Output: "IPAddress": "172.19.0.6"
```

## Pros and Cons

**Direct IP Routing**:
- ✅ Reliable when container IP is static
- ✅ Bypasses Docker DNS issues
- ✅ Explicit routing control
- ❌ Less flexible if container IP changes
- ❌ Requires manual IP management
- ❌ Breaks if container is recreated with different IP

**Container Name Routing**:
- ✅ Automatic service discovery
- ✅ Handles container recreation
- ✅ Standard Docker networking pattern
- ❌ Dependent on Docker DNS
- ❌ May have resolution delays
- ❌ Less explicit routing control

## MDDB API Routing

The MDDB API still uses container name routing:
```caddy
# MDDB API
handle /api/mddb/* {
	reverse_proxy mddb:11023
	encode gzip
}
```

This shows both patterns can coexist in the same Caddyfile based on specific service requirements.

## Related Documentation

- `stacks/web/Caddyfile` - Current Caddy configuration
- `docs/ssot/infrastructure/ssot.services.yml` - Service definitions
- `docs/ssot/infrastructure/ssot.health.yml` - Health check endpoints

## Date Added

2026-08-12
