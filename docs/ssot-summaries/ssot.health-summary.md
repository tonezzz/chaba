---
title: SSOT Health Configuration Summary
description: Health check endpoint definitions and recovery guidance for all Chaba services with location-specific configurations
tags: [ssot, health-check, services, configuration, monitoring]
ssot_source: docs/ssot/infrastructure/ssot.health.yml
created: 2026-08-06
updated: 2026-08-06
category: configuration
related: [health-check.md, ssot.health.home.yml, ssot.health.mobile.yml]
search_keywords: [health check, service monitoring, recovery actions, service endpoints, location-specific config]
---

# SSOT Health Configuration Summary

**Abstract**: Comprehensive health check configuration for all Chaba infrastructure services including web, API, datastore, GPU, and queue services with location-specific overrides and automated recovery guidance.

## Overview

The SSOT health configuration defines health check endpoints, timeout values, category classifications, and recovery actions for all Chaba services. It provides the foundation for the health check dashboard and automated monitoring systems.

## Purpose

Standardizes health monitoring across all services with:
- Consistent endpoint patterns and timeout values
- Category-based service classification (web, api, datastore, gpu, queue, optional)
- Location-specific configuration (home vs mobile)
- Automated recovery guidance for common failure modes

## Services Defined

### Web Services
- **web**: Main web application health check
- **status-api**: System status API providing hardware metrics

### API Services  
- **trade-api**: Trading API endpoint
- **yomi-api**: Yomi LINE web application API
- **camera-control**: Camera management API

### Datastore Services
- **postgres**: PostgreSQL database
- **redis**: Redis cache service

### GPU Services
- **imagen2**: Image generation service (port 8000)
- **thai-legal-inference**: Thai legal LLM service (port 8001) - *Offline due to GPU memory constraints*
- **txt2vid**: Text-to-video service (port 8002) - *Offline due to GPU memory constraints*

### Queue Services
- **gpu-queue**: GPU job queue management system

### Optional Services
- **frigate**: NVR service (offline since 2026-08-14, on-demand only)

## Key Configuration Patterns

### Health Check Endpoints
- Standard pattern: `/health` or `/api/health`
- HTTP status code: 200 for healthy
- Timeout: 10 seconds (default)
- Container health checks for Docker services

### Category-Based Filtering
Services are categorized for dashboard filtering:
- **web**: User-facing web applications
- **api**: Backend API services
- **datastore**: Database and cache services
- **gpu**: GPU-accelerated services
- **queue**: Job queue systems
- **optional**: On-demand services

### Location-Specific Configuration
- **ssot.health.yml**: Location-agnostic base configuration
- **ssot.health.home.yml**: Home network (tony-omen.local, tony-dell.local)
- **ssot.health.mobile.yml**: Mobile/remote (localhost, VPN paths)

## Recovery Actions

### Standard Recovery Patterns
- **Service restart**: Docker container restart
- **Health check verification**: Repeated endpoint testing
- **Log analysis**: Container log review
- **Dependency checks**: Verify dependent services are healthy

### GPU-Specific Recovery
- **GPU memory high**: Identify processes using GPU memory, hold llama if needed
- **GPU service failures**: Check GPU access, nvidia-smi availability
- **Queue stuck jobs**: Cancel stuck jobs, clean up queue

### API Service Recovery
- **Endpoint failures**: Check service logs, verify configuration
- **Timeout issues**: Increase timeout values, check network connectivity
- **Dependency failures**: Verify database/cache connectivity

## Configuration Structure

### Service Definition Format
```yaml
- id: service-name
  name: Display Name
  url: http://hostname:port/health
  timeout: 10
  category: service-category
  note: Optional status notes
```

### Location Override Pattern
Location-specific files override base configuration:
- Add location-specific hostnames
- Adjust timeout values for remote access
- Add location-specific notes
- Enable/disable services based on location

## Integration Points

### Health Check Dashboard
- Primary consumer of SSOT health configuration
- Auto-detects location and loads appropriate config
- Displays service status with category filtering
- Provides recovery action guidance

### Automated Monitoring
- Overnight assessment script uses health endpoints
- System automation scripts reference health check patterns
- GPU monitoring integrates with GPU service health checks

### API Integration
- Status API provides unified health check endpoint
- Yomi API health monitoring
- GPU queue API health status

## Full Configuration

For complete YAML configuration including all service definitions, timeout values, and recovery actions, see the authoritative source:
- **Base Configuration**: `docs/ssot/infrastructure/ssot.health.yml`
- **Home Configuration**: `docs/ssot/infrastructure/ssot.health.home.yml`
- **Mobile Configuration**: `docs/ssot/infrastructure/ssot.health.mobile.yml`

## Related Documentation

- **Health Check Dashboard**: `docs/kb/health-check.md` - Dashboard implementation and usage
- **System Automation**: `docs/kb/system-automation.md` - Automated monitoring procedures
- **GPU Configuration**: `docs/ssot/infrastructure/ssot.gpu.yml` - GPU service details
- **SSOT Index**: `docs/ssot/ssot.index.yml` - Master SSOT file index

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-06 | Created SSOT health configuration summary | devin |
