# SSOT Infrastructure Summary

**Purpose**: Summary of SSOT infrastructure configuration for searchability via MCP docs server.

## Health Check Configuration

**File**: `docs/ssot/infrastructure/ssot.health.yml`
**Purpose**: Health check endpoint definitions and recovery guidance for all services
**Scope**: Location-agnostic health check definitions
**Services**: Web services, databases, APIs, monitoring systems

### Location-Specific Health Configs

**Home Network**: `docs/ssot/infrastructure/ssot.health.home.yml`
- Uses tony-omen.local hostnames
- Home network specific endpoints
- Local service monitoring

**Mobile/Remote**: `docs/ssot/infrastructure/ssot.health.mobile.yml`
- Uses localhost or VPN paths
- Remote access configurations
- Mobile service monitoring

## GPU Configuration

**File**: `docs/ssot/infrastructure/ssot.gpu.yml`
**Purpose**: GPU policy, VRAM budget, queue implementation details
**Key Components**:
- GPU memory allocation and budgeting
- Queue system for GPU resource management
- Systemd services for GPU services
- MCP tool reference for GPU operations
- Service prioritization and backpressure

## Services Configuration

**File**: `docs/ssot/infrastructure/ssot.services.yml`
**Purpose**: Service configuration summary
**Services Covered**:
- llama-router: LLM model routing
- postgres: Database configuration
- Container details and orchestration
- API endpoints and integration points

## Automation Configuration

**File**: `docs/ssot/infrastructure/ssot.automation.yml`
**Purpose**: Automated monitoring and maintenance schedules
**Automation Tasks**:
- GPU monitoring (5-minute intervals)
- System maintenance (3 AM daily)
- Overnight assessment (2 AM daily)
- Health check scheduling
- Automated cleanup and maintenance

## Disaster Recovery Infrastructure

**File**: `docs/ssot/infrastructure/ssot.disaster-recovery.yml`
**Purpose**: Disaster recovery infrastructure documentation
**Components**:
- Backup scripts and schedules
- Recovery procedures
- Verification status
- Automation schedules
- Restore point management

## Related Documentation

- **SSOT Index**: `docs/ssot/ssot.index.yml` - Master index of all SSOT files
- **System Automation**: `docs/kb/system-automation.md` - Automation implementation details
- **Health Check**: `docs/kb/health-check.md` - Health check procedures
- **GPU Service**: `docs/kb/gpu-embedding-service.md` - GPU queue and service details

## Search Keywords

health check, gpu configuration, services, automation, disaster recovery, monitoring, maintenance, llama-router, postgres, gpu queue, system automation, backup, recovery
