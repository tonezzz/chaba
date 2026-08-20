---
category: operations
---

# Health Check Dashboard
## What it is

title: Health Check Dashboard


**Abstract**: Real-time system health monitoring dashboard providing unified view of service status, GPU metrics, and Yomi API health with auto-refresh, category-based filtering, and location-specific configuration support.
## Context/Background

Created 2026-08-04 as part of Chaba infrastructure documentation.


## Overview

Real-time system health monitoring dashboard served from `http://tony-omen.local:8080/apps/health-check/` (home) or `http://localhost:8080/apps/health-check/` (mobile).

## Purpose

Provides unified real-time monitoring of all Chaba infrastructure services with category-based filtering, automatic location detection, and comprehensive troubleshooting guidance for service failures.

## Key files

| File | Purpose |
|------|---------|
| `chaba/stacks/web/public/apps/health-check/index.html` | Main dashboard HTML with tab navigation |
| `chaba/stacks/web/public/apps/health-check/health-check.js` | Dashboard logic, health checks, tab switching |
| `chaba/stacks/web/public/apps/health-check/health-check.css` | Dashboard styling |
| `chaba/docs/ssot/infrastructure/ssot.health.yml` | Service definitions and recovery actions |
| `chaba/docs/ssot/infrastructure/ssot.health.home.yml` | Home location-specific config |
| `chaba/docs/ssot/infrastructure/ssot.health.mobile.yml` | Mobile location-specific config |

## Location Detection

The dashboard auto-detects location (home vs mobile) by trying to reach local endpoints:
- Home: `http://tony-dell.local:8080/api/status` or `http://tony-omen.local:8080/api/status`
- Mobile: Fallback if home endpoints unreachable

Location-specific SSOT configs are loaded based on detected location.

## Caddyfile Routing

Important routing rules in `chaba/stacks/web/Caddyfile`:
- `/api/gpu/*` → `status-api:8000` (must use `handle`, not `handle_path`)
- `/api/gpu-queue/*` → `host.docker.internal:3001`
- `/api/yomi/*` → `host.docker.internal:3000`
- `/api/*` → `status-api:8000` (catchall for other APIs)

## Related Documentation

- **SSOT Health Configuration**: `docs/ssot/infrastructure/ssot.health.yml` - Service definitions and recovery actions
- **GPU Embedding Service**: `docs/kb/gpu-embedding-service.md` - GPU service integration and monitoring
- **System Automation**: `docs/kb/system-automation.md` - Automated monitoring and maintenance scripts
- **SSOT GPU Configuration**: `docs/ssot/infrastructure/ssot.gpu.yml` - GPU policy and queue implementation

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-01 | Initial creation | tony |
| 2026-08-03 | GPU service health checks, Txt2Vid migration | tony |
| 2026-08-03 | Enhanced GPU queue monitoring with job type breakdown | tony |
| 2026-08-06 | Added frontmatter metadata, standardized structure | devin |

## Tags

- **docker**: docker
- **containers**: containers
- **containerization**: containerization
- **gpu**: gpu
- **nvidia**: nvidia
- **cuda**: cuda
- **ml**: ml
- **ai**: ai
- **yomi**: yomi
- **line**: line
- **messaging**: messaging
- **conversations**: conversations
- **api**: api
- **rest**: rest
- **http**: http
- **web**: web
- **monitoring**: monitoring
- **health**: health
- **metrics**: metrics
- **logging**: logging
- **documentation**: documentation
- **kb**: kb
- **knowledge-base**: knowledge-base
- **ssot**: ssot
- **configuration**: configuration
- **infrastructure**: infrastructure
- **2026**: 2026

## See also

- [Health Check Api](health-check-api.md)
- [Health Check Tabs](health-check-tabs.md)
- [Health Check Troubleshooting](health-check-troubleshooting.md)
