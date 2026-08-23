# Container Security First Pass 2026-08-18

## What it is

Container Security First Pass 2026-08-18

## Context/Background

**Date:** 2026-08-18
**Session Context:** 

## Key Details

### Technical Details
Container security first pass (2026-08-18):
- Removed stale `web-status-api:latest` image from tony-omen.
- Bumped `web` Caddy image from `caddy:2-alpine` to `caddy:latest` in chaba-omen/stacks/web/docker-compose.yml.
- Bumped `gpu-queue` and `gpu-queue-processor` from `node:20-alpine` to `node:22-alpine` in chaba/stacks/web/docker-compose.yml and ssot.services.yml.
- Pulled/recreated `ollama/ollama:latest` and `node:22-alpine` for gemini-ollama-proxy in chaba/stacks/web/mddb/docker-compose.yml.
- Verified health endpoints for ollama (11434), gemini-ollama-proxy (11435), web (8080), gpu-queue (3001).
- Left `imagen2-inference` untouched (386 vulns; requires model-aware rebuild due to PyTorch/transformers versions).

Conventions:
- Node-based GPU queue and proxy services should use `node:22-alpine` to receive upstream security fixes.
- Caddy should track `caddy:latest` for regular rebuilds.
- Stale container images (`web-status-api`) should be removed after replacement to keep scan surface clean.

### Implementation
- **Status:** Documented
- **Date:** 2026-08-18
- **Location:** docs/kb/

## Related Documentation

- **[KB Migration Summary](kb-migration-summary-2026-08-13.md)** - Related migration work

## Tags

- **infrastructure**: System infrastructure changes
- **documentation**: Knowledge base documentation
- **migration**: System migration and updates
