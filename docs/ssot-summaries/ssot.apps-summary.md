---
title: SSOT Applications Registry Summary
description: App registry with all application names and per-host deployment mappings for Chaba infrastructure
tags: [ssot, apps, deployment, registry, configuration]
ssot_source: docs/ssot/apps/ssot.apps.yml
created: 2026-08-06
updated: 2026-08-06
category: configuration
related: [ssot.apps.chaba.yml, ssot.apps.playlive.yml, ssot.apps.track4.yml]
search_keywords: [applications, deployment, app registry, per-host config, chaba apps]
---

# SSOT Applications Registry Summary

**Abstract**: Central application registry defining all Chaba infrastructure applications with per-host deployment mappings, service configurations, and integration points for consistent deployment across multiple environments.

## Overview

The SSOT applications registry serves as the single source of truth for all Chaba applications, defining application names, deployment targets, service configurations, and host-specific mappings for consistent infrastructure management.

## Purpose

Standardizes application deployment with:
- Central application registry with unique identifiers
- Per-host deployment mappings (tony-omen, tony-dell, chaba.h3)
- Service configuration references
- Integration point documentation
- Deployment status tracking

## Application Categories

### Web Applications
- **chaba**: Main Chaba infrastructure web application
- **playlive**: Browser automation service
- **track4**: Course simulator application
- **cams**: Camera monitoring application
- **map3d**: 3D map viewer with point clouds
- **wind**: Wind forecast page for Track4
- **aihub**: Multi-AI browser automation via Playlive
- **deka**: Deka application

### AI/ML Services
- **imagen2**: Image generation service
- **imagen3**: Next-generation image generation
- **thai-legal**: Thai legal document processing

### Infrastructure Services
- **status-api**: System status and health monitoring
- **gpu-queue**: GPU job queue management
- **yomi-api**: Yomi LINE web application API
- **trade-api**: Trading API service

## Deployment Architecture

### Host Mappings
Applications are deployed across multiple hosts:
- **tony-omen.local**: Primary development and GPU host
- **tony-dell.local**: Secondary development host
- **chaba.h3.gizmo-thailand.com**: Production static site

### Deployment Patterns
- **Docker containers**: Most services run in Docker
- **Systemd services**: Critical infrastructure services
- **Static sites**: Web applications served via Caddy
- **GPU services**: Hosted on tony-omen for GPU access

## Application Configuration Structure

### Standard App Definition
```yaml
app-name:
  display_name: Display Name
  description: Application description
  hosts:
    tony-omen:
      url: http://tony-omen.local/path
      type: docker|systemd|static
      status: active|offline
    tony-dell:
      url: http://tony-dell.local/path
      type: docker|systemd|static
      status: active|offline
```

### Service Integration
- **Database**: PostgreSQL integration for data persistence
- **Cache**: Redis integration for caching
- **GPU**: GPU service integration for AI/ML workloads
- **API**: REST API integration between services

## Key Applications

### Chaba Main Application
- **Purpose**: Infrastructure management dashboard
- **Deployment**: tony-omen.local, tony-dell.local
- **Components**: Health check, status pages, documentation
- **Integration**: All infrastructure services

### Playlive Browser Automation
- **Purpose**: Browser automation for testing and scraping
- **Deployment**: tony-omen.local, tony-dell.local
- **Features**: Session management, tool integration
- **Integration**: AI Hub, Track4 testing

### Track4 Course Simulator
- **Purpose**: Golf course simulation and analysis
- **Deployment**: tony-omen.local
- **Features**: 3D visualization, wind data
- **Integration**: Wind forecast, Map3D

### GPU Services
- **Imagen2/Imagen3**: Image generation
- **Thai Legal**: Document processing
- **GPU Queue**: Job orchestration
- **Deployment**: tony-omen.local (GPU host)

## Deployment Status

### Active Services
- Web applications (chaba, playlive, track4)
- Infrastructure services (status-api, gpu-queue, yomi-api)
- GPU services (subject to VRAM availability)

### Offline Services
- Some GPU services (due to memory constraints)
- Optional services (on-demand only)
- Development services (environment-specific)

## Integration Points

### SSOT Integration
- **Health Configuration**: Service health check definitions
- **GPU Configuration**: GPU service deployment details
- **Services Configuration**: Container and service details

### Documentation Integration
- **Per-app documentation**: Individual app configuration files
- **KB entries**: Operational guides for each app
- **Architecture docs**: System design and integration

## Configuration Management

### App-Specific Files
- **Base registry**: `docs/ssot/apps/ssot.apps.yml`
- **Per-app configs**: `docs/ssot/apps/ssot.apps.{app-name}.yml`
- **Host-specific**: Location-specific deployment overrides

### Update Process
1. Update base registry with new applications
2. Create per-app configuration files
3. Define host-specific deployment mappings
4. Update integration points
5. Validate configuration consistency

## Operational Procedures

### Adding New Applications
1. Define application in base registry
2. Create per-app configuration file
3. Specify deployment targets and types
4. Configure service integrations
5. Update documentation

### Deployment Updates
1. Update deployment mappings in registry
2. Modify service configurations as needed
3. Update integration points
4. Test deployment on target hosts
5. Update documentation

### Status Monitoring
- Health check integration for status tracking
- GPU queue integration for AI service status
- Automated monitoring via overnight assessment
- Manual verification via health dashboard

## Full Configuration

For complete YAML configuration including all application definitions, deployment mappings, and service configurations, see the authoritative sources:
- **Base Registry**: `docs/ssot/apps/ssot.apps.yml`
- **Per-App Configs**: `docs/ssot/apps/ssot.apps.{app-name}.yml`

## Related Documentation

- **SSOT Index**: `docs/ssot/ssot.index.yml` - Master SSOT file index
- **Health Configuration**: `docs/ssot/infrastructure/ssot.health.yml` - Service health definitions
- **GPU Configuration**: `docs/ssot/infrastructure/ssot.gpu.yml` - GPU service details
- **Services Configuration**: `docs/ssot/infrastructure/ssot.services.yml` - Container details

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-06 | Created SSOT applications registry summary | devin |
