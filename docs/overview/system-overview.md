---
title: Chaba Infrastructure System Overview
description: Comprehensive overview of the Chaba infrastructure including all major systems, their integration points, operational procedures, and architecture
tags: [overview, infrastructure, architecture, systems, operations]
created: 2026-08-13
updated: 2026-08-13
category: architecture
related: [docs/runbooks/backup-system-operations.md, docs/runbooks/monitoring-dashboard-operations.md, docs/runbooks/security-audit-operations.md, docs/ssot/infrastructure/ssot.automation.yml]
search_keywords: [overview, infrastructure, systems, architecture, integration, operations]
---

# Chaba Infrastructure System Overview

**Abstract**: Comprehensive overview of the Chaba infrastructure including all major systems (backup, monitoring, security, GPU queue, Yomi, web services), their integration points, operational procedures, and architecture. This document provides a high-level view of the entire infrastructure ecosystem.

## Overview

The Chaba infrastructure is a comprehensive system designed for AI model development, web services, data processing, and operational automation. It consists of multiple integrated systems including automated backup to Google Drive, real-time monitoring dashboard, security audit and hardening, GPU queue management, Yomi LINE integration, and various web services.

## System Architecture

### Core Systems

1. **Backup System**
   - **Purpose**: Automated backup to Google Drive with FUSE compatibility
   - **Components**: backup-manager.sh, backup-monitor.sh, restore-manager.sh
   - **Storage**: Google Drive (/home/tony/GoogleDrive/Tony AI/backup/chaba)
   - **Schedule**: Daily at 2:00 AM (systemd timer)
   - **Retention**: 30 days daily, 12 weeks weekly, 6 months monthly

2. **Monitoring Dashboard**
   - **Purpose**: Real-time infrastructure monitoring and alerting
   - **Components**: monitoring-dashboard.mjs, systemd service
   - **Access**: http://localhost:3002
   - **Update Interval**: 30 seconds auto-refresh
   - **API**: JSON endpoints for integration

3. **Security Audit System**
   - **Purpose**: Security vulnerability scanning and hardening
   - **Components**: security-audit.sh, security-harden.sh
   - **Schedule**: Weekly recommended
   - **Coverage**: File permissions, Docker, network, database, credentials

4. **GPU Queue System**
   - **Purpose**: GPU workload scheduling and management
   - **Components**: gpu-queue service, intelligent scheduling
   - **Features**: Memory-aware scheduling, duration prediction, dynamic priority
   - **Database**: PostgreSQL with optimized connection pooling

5. **Yomi System**
   - **Purpose**: LINE conversation integration and processing
   - **Components**: yomi-api, yomi-fetch, yomi-process services
   - **Database**: PostgreSQL with MCP health monitoring
   - **Features**: Message processing, summarization, rate limiting

6. **Web Services**
   - **Components**: Caddy (reverse proxy), status-api, trade-api
   - **Ports**: 8080/8081 (Caddy), various API ports
   - **Reverse Proxy**: Caddy with SSL termination
   - **Load Balancing**: Service routing and health checks

### Integration Points

**System Dependencies**:
- Backup System → Google Drive (FUSE mount), Docker, PostgreSQL
- Monitoring Dashboard → Health monitor logs, Docker, GPU (nvidia-smi)
- Security Audit → Git, Docker, PostgreSQL, File system
- GPU Queue → PostgreSQL, GPU (nvidia-smi), Docker
- Yomi → PostgreSQL, LINE API, MCP health server
- Web Services → Docker, PostgreSQL, Redis, Weaviate

**Data Flow**:
1. **Backup**: Local temp → Google Drive (FUSE compatibility)
2. **Monitoring**: Services → Health monitor → Dashboard → API
3. **Security**: File system → Audit → Report → Hardening
4. **GPU Queue**: Jobs → PostgreSQL → GPU → Results → Database
5. **Yomi**: LINE → API → Database → Processing → Storage
6. **Web**: Client → Caddy → Services → Databases → Response

## Operational Procedures

### Daily Operations

**Automated Tasks**:
- 2:00 AM: Full backup to Google Drive
- Hourly: Backup monitoring and health checks
- Every 10 minutes: Health monitor (CPU, memory, disk, services)
- Continuous: GPU queue processing and scheduling

**Manual Tasks**:
- Review monitoring dashboard for issues
- Check backup completion status
- Review security alerts if any
- Monitor GPU queue performance

### Weekly Operations

**Maintenance Tasks**:
- Run security audit (recommended)
- Review backup retention and cleanup
- Check system resource trends
- Review alert patterns and frequency
- Update documentation if needed

### Monthly Operations

**Strategic Tasks**:
- Comprehensive security review
- Backup restoration testing
- Performance baseline analysis
- Capacity planning review
- Documentation updates

## Key Locations

### Scripts
- `/home/tony/CascadeProjects/chaba/scripts/` - Main scripts directory
- `backup-manager.sh` - Backup automation
- `backup-monitor.sh` - Backup monitoring
- `restore-manager.sh` - Backup restoration
- `monitoring-dashboard.mjs` - Monitoring dashboard
- `security-audit.sh` - Security audit
- `security-harden.sh` - Security hardening
- `overnight-jobs-expanded.sh` - Comprehensive overnight assessment

### Configuration
- `/home/tony/CascadeProjects/chaba/stacks/web/` - Docker Compose configs
- `/home/tony/CascadeProjects/chaba/systemd/` - Systemd services
- `/home/tony/CascadeProjects/chaba/docs/ssot/` - SSOT documentation
- `/home/tony/CascadeProjects/chaba/.env` - Environment variables

### Data Storage
- `/home/tony/GoogleDrive/Tony AI/backup/chaba/` - Backup storage
- Docker volumes: postgres_data, redis_data, weaviate_data
- PostgreSQL: chaba database (GPU queue, Yomi, health monitoring)
- Redis: Caching and session storage

### Logs
- `/home/tony/CascadeProjects/chaba/logs/` - Application logs
- `/var/log/chaba-backup.log` - Backup operation logs
- `/var/log/chaba-backup-monitor.log` - Backup monitoring logs
- Systemd journal: Service logs and health monitor

## System Health Monitoring

### Health Check Integration
- **Service**: chaba-health-monitor.timer (every 10 minutes)
- **Coverage**: CPU frequency, temperature, memory, disk, services, Google Drive
- **Alerting**: Critical/warning/info severity levels
- **Integration**: MCP health server for historical analysis

### Monitoring Dashboard
- **Real-time**: Service status, performance metrics, alerts
- **Historical**: Alert history, backup status, GPU trends
- **API**: JSON endpoints for external monitoring tools
- **Auto-refresh**: 30-second update interval

### Backup Monitoring
- **Schedule**: Hourly checks
- **Coverage**: Freshness, size, integrity, completeness, rotation
- **Alerting**: Critical for backup failures, warnings for issues
- **Reports**: Detailed monitoring reports with recommendations

## Security Architecture

### Security Layers
1. **File Permissions**: Environment files (600), logs (640), sensitive files restricted
2. **Docker Security**: Container isolation, user directives (in progress)
3. **Network Security**: Interface binding restrictions (in progress)
4. **Database Security**: Authentication methods (trust → md5 planned)
5. **Credential Management**: Environment variables, no hardcoding
6. **Backup Security**: Google Drive encryption, access controls

### Security Automation
- **Audit**: Comprehensive vulnerability scanning
- **Hardening**: Automated fixes for common issues
- **Monitoring**: Security alerts and recommendations
- **Reporting**: Detailed security reports with prioritized action items

## Performance Optimization

### Database Optimization
- **Connection Pooling**: Optimized PostgreSQL pool (max 20, min 2)
- **Query Monitoring**: Slow query detection (1 second threshold)
- **Index Analysis**: Index usage and missing index recommendations
- **Caching**: Redis integration for query result caching

### GPU Optimization
- **Intelligent Scheduling**: Memory-aware scheduling, duration prediction
- **Dynamic Priority**: Automatic priority adjustment based on job behavior
- **Resource Monitoring**: GPU memory, temperature, utilization tracking
- **Queue Management**: Priority queues, fair scheduling, failure handling

### Caching Strategy
- **API Caching**: Redis-backed API response caching
- **Database Caching**: Query result caching with TTL
- **Static Content**: Caddy static file caching
- **GPU Results**: Cached GPU computation results

## Disaster Recovery

### Backup Strategy
- **Daily Backups**: Full system backup to Google Drive
- **Incremental**: Changed files only (planned)
- **Retention**: 30 days daily, 12 weeks weekly, 6 months monthly
- **Verification**: Backup integrity checks and restoration testing

### Restoration Procedures
- **Database**: Point-in-time restoration from SQL dumps
- **Volumes**: Docker volume restoration from tar archives
- **Configurations**: Configuration file restoration
- **Documentation**: Documentation restoration from backups

### Recovery Testing
- **Monthly**: Backup restoration testing
- **Quarterly**: Full disaster recovery drill
- **Documentation**: Updated runbooks and procedures

## Scaling Considerations

### Horizontal Scaling
- **Web Services**: Multiple instances behind Caddy load balancer
- **GPU Queue**: Multiple queue processors
- **Database**: Read replicas for query scaling
- **Cache**: Redis cluster for distributed caching

### Vertical Scaling
- **GPU**: Additional GPU cards for parallel processing
- **Database**: Increased memory and CPU for PostgreSQL
- **Storage**: Expanded Google Drive storage capacity
- **Network**: Increased bandwidth for data transfer

## Related Documentation

### Runbooks
- **Backup System Operations**: `docs/runbooks/backup-system-operations.md`
- **Monitoring Dashboard Operations**: `docs/runbooks/monitoring-dashboard-operations.md`
- **Security Audit Operations**: `docs/runbooks/security-audit-operations.md`

### SSOT Documentation
- **Infrastructure Automation**: `docs/ssot/infrastructure/ssot.automation.yml`
- **Health Configuration**: `docs/ssot/infrastructure/ssot.health.yml`
- **Services Configuration**: `docs/ssot/infrastructure/ssot.services.yml`

### Knowledge Base
- **Google Drive Backup System**: `docs/kb/google-drive-backup-system.md`
- **MCP Health PostgreSQL Migration**: `docs/kb/mcp-health-postgresql-migration.md`
- **System Automation**: `docs/kb/system-automation.md`
- **Health Check**: `docs/kb/health-check.md`

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-13 | Initial creation with comprehensive system overview | Devin |