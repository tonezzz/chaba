---
category: operations
---

# PlayLive Basic Authentication

## What it is

PlayLive browser automation daemon extended with basic authentication support to enable verification of Caddy-protected pages like Yomi web interface.
## Context/Background

Created 2026-08-04 as part of Chaba infrastructure documentation.


## Context

PlayLive is a remote browser-control facility that lets multiple AI clients drive Chrome/Playwright sessions through a shared daemon. Previously, it could not access pages protected by HTTP basic authentication, limiting verification capabilities for protected services like Yomi.

## Related Documentation

- `docs/ssot/apps/ssot.apps.playlive.yml` - PlayLive SSOT documentation
- `chaba/stacks/web/Caddyfile` - Caddy configuration with basic auth
- `chaba/stacks/web/.env` - Environment variables including password hashes
- `docs/kb/yomi.md` - Yomi web application documentation

## Tags

- **docker**: docker
- **containers**: containers
- **containerization**: containerization
- **yomi**: yomi
- **line**: line
- **messaging**: messaging
- **conversations**: conversations
- **security**: security
- **scanning**: scanning
- **vulnerability**: vulnerability
- **documentation**: documentation
- **kb**: kb
- **knowledge-base**: knowledge-base
- **workflow**: workflow
- **automation**: automation
- **mcp**: mcp
- **ssot**: ssot
- **configuration**: configuration
- **infrastructure**: infrastructure
- **playwright**: playwright
- **testing**: testing
- **playlive**: playlive
- **browser**: browser
- **yaml**: yaml
- **syntax**: syntax
- **2026**: 2026

## See also

- [Playlive Authentication Implementation](playlive-authentication-implementation.md)
- [Playlive Authentication Services](playlive-authentication-services.md)
