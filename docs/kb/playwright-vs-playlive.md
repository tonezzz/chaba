---
category: operations
---

# Playwright vs PlayLive Comparison
## What it is

Playwright and PlayLive serve different purposes in the browser automation ecosystem. Playwright is a browser automation library primarily for testing, while PlayLive is a session management daemon built on Playwright for AI-driven interactive workflows.

## Context/Background

Created 2026-08-05 as part of Chaba infrastructure documentation.


## Overview

Playwright and PlayLive serve different purposes in the browser automation ecosystem. Playwright is a browser automation library primarily for testing, while PlayLive is a session management daemon built on Playwright for AI-driven interactive workflows.

## Architecture Relationship

```
PlayLive MCP Server (playlived.mjs)
    ↓ uses
Playwright (browser automation library)
    ↓ controls
Chrome/Chromium browsers
```

PlayLive is a custom layer built on top of Playwright that adds session management, MCP integration, and multi-client support.

## Related Documentation

- `docs/kb/playlive-authentication.md` - PlayLive authentication implementation
- `docs/ssot/apps/ssot.apps.playlive.yml` - PlayLive SSOT documentation
- `chaba-tony-dell/mcp-servers/mcp-playlive/playlived.mjs` - PlayLive daemon implementation
- `chaba-tony-dell/mcp-servers/mcp-playlive/playlive-server.py` - PlayLive MCP client

## Tags

- **api**: api
- **rest**: rest
- **http**: http
- **web**: web
- **monitoring**: monitoring
- **health**: health
- **metrics**: metrics
- **logging**: logging
- **deployment**: deployment
- **ci**: ci
- **cd**: cd
- **docker**: docker
- **performance**: performance
- **optimization**: optimization
- **caching**: caching
- **testing**: testing
- **e2e**: e2e
- **automation**: automation
- **documentation**: documentation
- **kb**: kb
- **knowledge-base**: knowledge-base
- **workflow**: workflow
- **mcp**: mcp
- **ssot**: ssot
- **configuration**: configuration
- **infrastructure**: infrastructure
- **raceman**: raceman
- **php**: php
- **worktree**: worktree
- **playwright**: playwright
- **playlive**: playlive
- **browser**: browser
- **language**: language
- **detection**: detection
- **nlp**: nlp
- **2026**: 2026

## See also

- [Playwright Vs Playlive Comparison](playwright-vs-playlive-comparison.md)
- [Playwright Vs Playlive Operations](playwright-vs-playlive-operations.md)
- [Playwright Vs Playlive Setup](playwright-vs-playlive-setup.md)
