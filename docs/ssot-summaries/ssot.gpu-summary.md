---
title: SSOT GPU Configuration Summary
description: GPU policy, VRAM budget, queue implementation details, systemd services, and MCP tool reference for GPU resource management
tags: [ssot, gpu, vram, queue, policy, resource-management]
ssot_source: docs/ssot/infrastructure/ssot.gpu.yml
created: 2026-08-06
updated: 2026-08-06
category: configuration
related: [gpu-embedding-service.md, health-check.md, ssot.health.yml]
search_keywords: [GPU policy, VRAM budget, GPU queue, resource management, CUDA, models]
---

# SSOT GPU Configuration Summary

**Abstract**: Comprehensive GPU resource management configuration including VRAM budget policies, model specifications, queue implementation details, systemd services, and MCP tool integration for Chaba infrastructure.

## Overview

The SSOT GPU configuration defines policies and procedures for GPU resource management across Chaba infrastructure, including VRAM budget allocation, model specifications, queue implementation, and monitoring integration.

## Purpose

Standardizes GPU resource management with:
- VRAM budget allocation and monitoring
- Model loading policies and priorities
- GPU queue implementation details
- Systemd service configurations
- MCP tool integration for GPU operations

## GPU Policy

### VRAM Budget
- **Total VRAM**: 24GB (NVIDIA GPU)
- **Available for AI**: ~16GB (system overhead reserved)
- **Budget Allocation**: Per-service VRAM limits
- **Monitoring**: Real-time VRAM usage tracking via Netdata

### Model Loading Policies
- **Priority-based loading**: Critical services load first
- **VRAM checking**: Verify available VRAM before model load
- **Fallback policies**: Graceful degradation when VRAM insufficient
- **Model unloading**: Automatic unloading of unused models

## Model Specifications

### Active Models
- **Phi-3-mini-4k-instruct-q4.gguf**: 2.3GB VRAM, MCP/chatllama integration
- **all-MiniLM-L6-v2**: 384 dimensions, embedding service

### Offline Models (GPU Memory Constraints)
- **thai-legal-gemma-4b-cpt.Q4_K_M.gguf**: 5GB VRAM - *Offline since 2026-08-06*
- **Imagen2 models**: Variable VRAM - *Offline since 2026-08-06*
- **Txt2Vid models**: Variable VRAM - *Offline since 2026-08-06*

### Model Loading Priority
1. **P1 (Highest)**: Embedding service (always available)
2. **P2**: Yomi summarization models
3. **P3**: Image generation (Imagen2)
4. **P4 (Lowest)**: Experimental models

## GPU Queue Implementation

### Queue Architecture
- **Database**: PostgreSQL with job tracking
- **Orchestrator**: Node.js job processing system
- **Monitoring**: Real-time status and metrics
- **Backpressure**: GPU-aware load management

### Job Types
- **embedding**: Text embedding jobs (2 concurrent max)
- **imagen2**: Image generation jobs (1 concurrent max)
- **txt2vid**: Text-to-video jobs (1 concurrent max)
- **llama**: LLM inference jobs (1 concurrent max)
- **yomi_summary**: Yomi conversation summarization (1 concurrent max)
- **yomi_daily**: Yomi daily summary generation (1 concurrent max)

### Priority System
- **P4**: embedding, yomi_summary, yomi_daily (highest priority)
- **P3**: txt2vid, cogvideo
- **P2**: imagen2
- **P1**: llama (lowest priority)

### Backpressure System
- **GPU monitoring**: Real-time utilization tracking via Netdata API
- **Threshold**: Processing paused when GPU > 80% utilization
- **Circuit breaker**: Automatic protection after 5 consecutive failures
- **Adaptive delays**: Dynamic wait times based on GPU load

## Systemd Services

### GPU Queue Service
- **Service**: `gpu-queue.service`
- **Implementation**: Node.js orchestrator
- **Auto-restart**: Enabled
- **Dependencies**: PostgreSQL, GPU access

### GPU Monitoring Service
- **Service**: `gpu-monitor.service`
- **Implementation**: Python monitoring script
- **Schedule**: Every 5 minutes
- **Alerts**: VRAM thresholds, temperature limits

### Embedding Service
- **Service**: `embedding-service.service`
- **Implementation**: Python Flask service
- **GPU access**: CUDA-enabled
- **Port**: 5000

## MCP Tool Integration

### MCP-GPU Server
- **Purpose**: GPU status and operations via MCP
- **Tools**: GPU status, process listing, VRAM monitoring
- **Integration**: Status API, health check dashboard
- **Location**: `chaba/mcp-servers/mcp-gpu/server.py`

### MCP-Llama Server
- **Purpose**: LLM inference via MCP
- **Tools**: Model loading, text generation, queue management
- **Integration**: GPU queue, Yomi summarization
- **Location**: `chaba/mcp-servers/mcp-llama/server.py`

## Monitoring Integration

### Netdata Integration
- **GPU dashboard**: http://tony-omen.local:8080/apps/netdata/
- **Metrics**: VRAM usage, utilization, temperature
- **Alerts**: Configurable thresholds for VRAM and temperature

### Health Check Integration
- **GPU tab**: Real-time GPU status in health dashboard
- **Service health**: Individual GPU service monitoring
- **Queue status**: GPU queue job status and metrics

### Custom Monitoring
- **GPU monitor script**: `scripts/gpu-monitor.mjs`
- **Queue monitoring**: `scripts/gpu-queue/monitoring.mjs`
- **Alert thresholds**: VRAM 80%/90%, temperature 75°C/85°C

## Operational Procedures

### GPU Resource Allocation
1. Check available VRAM before model load
2. Verify GPU utilization is below threshold
3. Load model with appropriate priority
4. Monitor VRAM usage during operation
5. Unload model when no longer needed

### Queue Management
1. Submit job with appropriate priority
2. Monitor queue status and GPU utilization
3. Handle backpressure when GPU > 80%
4. Process jobs with adaptive delays
5. Clean up completed/failed jobs

### Troubleshooting
- **High VRAM usage**: Identify processes, hold llama, check for stuck jobs
- **GPU service failures**: Check GPU access, nvidia-smi, container logs
- **Queue stuck jobs**: Cancel stuck jobs, clean up queue, restart orchestrator

## Configuration Structure

### GPU Policy Format
```yaml
gpu_policy:
  vram_budget:
    total: 24GB
    available: 16GB
    monitoring: netdata
  models:
    - name: model-name
      size: VRAM size
      priority: loading priority
      status: active/offline
```

### Queue Configuration Format
```yaml
gpu_queue:
  database: postgresql
  orchestrator: nodejs
  job_types:
    - type: job-type
      max_concurrent: number
      priority: P1-P4
```

## Full Configuration

For complete YAML configuration including all GPU policies, model specifications, queue details, and service configurations, see the authoritative source:
- **GPU Configuration**: `docs/ssot/infrastructure/ssot.gpu.yml`

## Related Documentation

- **GPU Embedding Service**: `docs/kb/gpu-embedding-service.md` - Embedding service details
- **Health Check Dashboard**: `docs/kb/health-check.md` - GPU monitoring integration
- **System Automation**: `docs/kb/system-automation.md` - GPU monitoring procedures
- **GPU Queue Schema**: `scripts/gpu-queue/schema.sql` - Database schema

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-06 | Created SSOT GPU configuration summary | devin |
