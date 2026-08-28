---
title: Automated Deployment Operations Runbook
description: Comprehensive operational procedures for the Chaba automated deployment system including CI/CD pipeline, testing, validation, rollback capabilities, and troubleshooting
tags: [deployment, cicd, operations, runbook, automation, rollback]
created: 2026-08-13
updated: 2026-08-13
category: operations
related: [scripts/deploy.sh, scripts/ci-pipeline.sh, systemd/chaba-ci-pipeline.service, docs/runbooks/backup-system-operations.md]
search_keywords: [deployment, cicd, pipeline, rollback, testing, automation]
---

# Automated Deployment Operations Runbook

**Abstract**: Complete operational guide for the Chaba automated deployment system including CI/CD pipeline, pre-deployment testing, deployment automation, rollback capabilities, and troubleshooting procedures.

## Overview

The Chaba automated deployment system provides safe infrastructure deployment with comprehensive testing, validation, and rollback capabilities. It includes pre-deployment backups, automated testing stages, service deployment, post-deployment validation, and automated rollback on failure.

## Purpose

- **Safe Deployment**: Pre-deployment backups and testing prevent breaking changes
- **Automated Testing**: Comprehensive test suite covering syntax, validation, and service health
- **Rollback Capabilities**: Automatic rollback to previous deployment on failure
- **CI/CD Pipeline**: Automated testing and validation pipeline
- **Deployment Reports**: Detailed deployment reports with service status
- **Integration**: Integration with existing backup, monitoring, and security systems

## Key Files

| File | Purpose |
|------|---------|
| `scripts/deploy.sh` | Main deployment automation script |
| `scripts/ci-pipeline.sh` | CI/CD pipeline automation script |
| `systemd/chaba-ci-pipeline.service` | Systemd service for CI/CD pipeline |
| `scripts/ci-pipeline.timer` | Systemd timer for scheduled CI/CD runs |
| `logs/deployment.log` | Deployment operation logs |
| `logs/ci-pipeline.log` | CI/CD pipeline logs |
| `deployments/backups/` | Pre-deployment backups |
| `deployments/rollbacks/` | Deployment snapshots for rollback |

## Deployment Architecture

### Deployment Stages
1. **Pre-deployment Backup**: Automatic backup of critical configurations
2. **Pre-deployment Testing**: Syntax checks, validation, system tests
3. **Service Deployment**: Docker Compose deployment with image pulls
4. **Post-deployment Validation**: Service health checks and endpoint testing
5. **Deployment Snapshot**: Save current state for rollback
6. **Report Generation**: Detailed deployment report with service status

### CI/CD Pipeline Stages
1. **Syntax Testing**: Shell script and Node.js script syntax validation
2. **Validation**: SSOT file validation and consistency checks
3. **Backup System**: Backup system functionality testing
4. **Monitoring Dashboard**: Monitoring dashboard testing
5. **Security Audit**: Security vulnerability scanning
6. **Service Health**: Critical service health checks

### Rollback Mechanism
- **Pre-deployment Backups**: Automatic backup before each deployment
- **Deployment Snapshots**: Save current state after successful deployment
- **Rollback Command**: One-command rollback to previous state
- **Service Restoration**: Automatic service restart with restored configuration

## Operational Procedures

### Manual Deployment

**Full Deployment**:
```bash
# Run full deployment with testing and validation
./scripts/deploy.sh deploy
```

**Deployment Process**:
1. Pre-deployment backup creation
2. Pre-deployment tests (syntax, validation, backup, monitoring, security)
3. Service deployment (Docker Compose)
4. Post-deployment validation (service health, endpoint testing)
5. Deployment snapshot creation
6. Deployment report generation

**Expected Output**:
- Pre-deployment backup file location
- Test results for all stages
- Service deployment status
- Post-deployment validation results
- Deployment report location

### Rollback Deployment

**Rollback to Previous State**:
```bash
# Rollback to previous deployment
./scripts/deploy.sh rollback
```

**Rollback Process**:
1. Find latest pre-deployment backup
2. Extract backup to restore configurations
3. Restart services with restored configuration
4. Validate service health after rollback

**Safety Features**:
- Automatic pre-deployment backup prevents data loss
- Rollback only uses validated backup states
- Service health checks after rollback
- Detailed rollback logging

### CI/CD Pipeline

**Run Full CI/CD Pipeline**:
```bash
# Run all CI/CD pipeline stages
./scripts/ci-pipeline.sh all
```

**Run Specific Stage**:
```bash
# Run specific test stage
./scripts/ci-pipeline.sh syntax
./scripts/ci-pipeline.sh validation
./scripts/ci-pipeline.sh backup
./scripts/ci-pipeline.sh monitoring
./scripts/ci-pipeline.sh security
./scripts/ci-pipeline.sh services
```

**Pipeline Stages**:
- **Syntax**: Shell script and Node.js script syntax validation
- **Validation**: SSOT file validation and consistency checks
- **Backup**: Backup system functionality testing
- **Monitoring**: Monitoring dashboard testing
- **Security**: Security vulnerability scanning
- **Services**: Critical service health checks

### Testing Only Mode

**Run Tests Without Deployment**:
```bash
# Run pre-deployment tests only
./scripts/deploy.sh test
```

**Use Cases**:
- Validate changes before deployment
- Test after configuration changes
- Validate infrastructure state
- Troubleshooting deployment issues

## Troubleshooting

### Issue: Pre-deployment Backup Fails

**Symptoms**:
- Deployment fails at backup stage
- Cannot create backup file
- Backup directory inaccessible

**Causes**:
- Insufficient disk space
- Backup directory permissions
- File system issues

**Solutions**:
```bash
# Check disk space
df -h

# Check backup directory permissions
ls -la deployments/backups/

# Create backup directory if needed
mkdir -p deployments/backups

# Check available space in Google Drive
df -h /home/tony/GoogleDrive
```

### Issue: Pre-deployment Tests Fail

**Symptoms**:
- Deployment fails at testing stage
- Syntax errors in scripts
- Validation failures

**Causes**:
- Script syntax errors
- SSOT validation issues
- Missing test dependencies

**Solutions**:
```bash
# Check syntax errors manually
bash -n scripts/your-script.sh
node -c scripts/your-script.mjs

# Run SSOT validation manually
./scripts/ssot-validate-sync.sh

# Check test dependencies
which bash node docker

# Fix identified issues before retrying deployment
```

### Issue: Service Deployment Fails

**Symptoms**:
- Docker Compose fails to start services
- Services not starting after deployment
- Image pull failures

**Causes**:
- Docker Compose configuration errors
- Network connectivity issues
- Image availability problems

**Solutions**:
```bash
# Check Docker Compose configuration
cd stacks/web
docker compose config

# Check Docker daemon status
docker ps

# Try manual deployment
docker compose up -d

# Check service logs
docker compose logs

# Pull images manually
docker compose pull
```

### Issue: Post-deployment Validation Fails

**Symptoms**:
- Services not healthy after deployment
- Web service not accessible
- API endpoints not responding

**Causes**:
- Service startup failures
- Network configuration issues
- Port conflicts

**Solutions**:
```bash
# Check service status
docker ps

# Check service logs
docker logs service_name

# Test web service manually
curl -v http://localhost:8080/

# Check port availability
netstat -tulpn | grep 8080

# Restart specific service
docker restart service_name
```

### Issue: Rollback Fails

**Symptoms**:
- Rollback command fails
- Cannot restore from backup
- Services not starting after rollback

**Causes**:
- Backup file corrupted
- Extraction failures
- Configuration conflicts

**Solutions**:
```bash
# Check backup file integrity
gzip -t deployments/backups/pre-deploy_*.tar.gz

# Verify backup contents
tar -tzf deployments/backups/pre-deploy_*.tar.gz

# Check available backups
ls -la deployments/backups/

# Manual rollback if automated fails
cd /home/tony/CascadeProjects/chaba
tar xzf deployments/backups/pre-deploy_*.tar.gz
cd stacks/web
docker compose up -d
```

### Issue: CI/CD Pipeline Fails

**Symptoms**:
- CI/CD pipeline fails at specific stage
- Test results not generated
- Pipeline report incomplete

**Causes**:
- Test script errors
- Missing dependencies
- Permission issues

**Solutions**:
```bash
# Check CI/CD logs
tail -f logs/ci-pipeline.log

# Run specific stage manually
./scripts/ci-pipeline.sh syntax
./scripts/ci-pipeline.sh validation

# Check test results directory
ls -la tests/results/

# Fix identified issues and re-run pipeline
```

## Performance Metrics

**Deployment Performance**:
- Pre-deployment backup: 5-10 seconds
- Pre-deployment testing: 30-60 seconds
- Service deployment: 30-60 seconds
- Post-deployment validation: 10-20 seconds
- Total deployment time: 2-3 minutes

**CI/CD Pipeline Performance**:
- Syntax testing: 5-10 seconds
- Validation: 10-20 seconds
- Backup testing: 10-20 seconds
- Monitoring testing: 10-20 seconds
- Security audit: 30-60 seconds
- Service health: 5-10 seconds
- Total pipeline time: 1-2 minutes

**Rollback Performance**:
- Backup extraction: 5-10 seconds
- Service restart: 20-30 seconds
- Validation: 10-20 seconds
- Total rollback time: 1-2 minutes

## Best Practices

### Deployment Best Practices
1. **Test Before Deploy**: Always run CI/CD pipeline before deployment
2. **Backup First**: Ensure pre-deployment backups are created
3. **Monitor After Deploy**: Monitor services for 30 minutes after deployment
4. **Review Reports**: Review deployment reports for any issues
5. **Test Rollback**: Periodically test rollback procedures

### CI/CD Best Practices
1. **Run Regularly**: Run CI/CD pipeline before major changes
2. **Fix Failures Promptly**: Address test failures immediately
3. **Update Tests**: Keep test suites updated with new features
4. **Monitor Pipeline**: Monitor pipeline execution time and trends
5. **Review Reports**: Review test reports for patterns

### Rollback Best Practices
1. **Test Rollback**: Periodically test rollback procedures
2. **Validate Backups**: Ensure backup files are valid
3. **Document Issues**: Document rollback scenarios and solutions
4. **Plan Rollback**: Know rollback procedures before deployment
5. **Monitor After Rollback**: Monitor services after rollback

## Related Documentation

- **Backup System Operations**: `docs/runbooks/backup-system-operations.md` - Backup system procedures
- **Monitoring Dashboard Operations**: `docs/runbooks/monitoring-dashboard-operations.md` - Monitoring procedures
- **Security Audit Operations**: `docs/runbooks/security-audit-operations.md` - Security procedures
- **System Overview**: `docs/overview/system-overview.md` - Infrastructure overview

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-13 | Initial creation with comprehensive deployment automation and CI/CD pipeline | Devin |