---
title: Security Audit Operations Runbook
description: Operational procedures for the Chaba security audit and hardening system including vulnerability scanning, security assessments, remediation procedures, and best practices
tags: [security, audit, operations, runbook, hardening, vulnerability]
created: 2026-08-13
updated: 2026-08-13
category: operations
related: [scripts/security-audit.sh, scripts/security-harden.sh, ssot.infrastructure/ssot.health.yml]
search_keywords: [security, audit, vulnerability, hardening, permissions, credentials]
---

# Security Audit Operations Runbook

**Abstract**: Complete operational guide for the Chaba security audit and hardening system including vulnerability scanning, file permissions analysis, Docker security checks, network security assessment, and automated remediation procedures.

## Overview

The Chaba security audit system provides comprehensive security analysis with automated vulnerability detection, file permissions auditing, Docker security checks, network security assessment, and automated hardening procedures. It includes severity classification, detailed reporting, and prioritized remediation recommendations.

## Purpose

- **Vulnerability Detection**: Automated scanning for security issues and misconfigurations
- **File Permissions**: Audit of sensitive file permissions and access controls
- **Docker Security**: Container security analysis and best practices validation
- **Network Security**: Open port monitoring and interface binding assessment
- **Credential Security**: Detection of hardcoded credentials and API keys
- **Automated Hardening**: Automatic fixes for common security issues
- **Reporting**: Detailed security reports with prioritized action items

## Key Files

| File | Purpose |
|------|---------|
| `scripts/security-audit.sh` | Main security audit script |
| `scripts/security-harden.sh` | Security hardening and remediation script |
| `logs/security-audit.log` | Security audit operation logs |
| `reports/security-audit-*.txt` | Detailed security audit reports |
| `reports/security-recommendations-*.txt` | Security hardening recommendations |

## Security Audit Architecture

### Audit Categories
1. **File Permissions**: Environment files, sensitive files, world-readable checks
2. **Git Security**: Credential exposure in git history, .env file commits
3. **Docker Security**: Root containers, socket permissions, user directives
4. **Network Security**: Open ports, interface binding, service exposure
5. **Systemd Security**: Service user directives, privilege escalation
6. **Backup Security**: Mount permissions, log access, directory permissions
7. **Database Security**: Authentication methods, network binding, pg_hba.conf
8. **API Key Security**: Hardcoded credentials in scripts, environment variable usage

### Severity Classification
- **High**: Immediate action required (credential exposure, insecure authentication)
- **Medium**: Plan within 1 week (container security, network exposure)
- **Low**: Next maintenance window (file permissions, logging)

### False Positive Filtering
- **Excluded Directories**: node_modules, venv, library files
- **File Patterns**: Test files, documentation, build artifacts
- **Known Safe**: Certificate files, configuration templates

## Operational Procedures

### Running Security Audit

**Full Security Audit**:
```bash
# Run comprehensive security audit
./scripts/security-audit.sh
```

**Expected Output**:
- Security issues found by severity
- Detailed issue descriptions
- Remediation recommendations
- Security report generation
- Exit code based on severity (1=high, 2=medium, 0=success)

**Audit Results**:
- Total issues count
- High/medium/low risk breakdown
- Report file location
- Immediate action requirements

### Security Hardening

**Automated Hardening**:
```bash
# Run security hardening
./scripts/security-harden.sh
```

**Auto-Fixed Issues**:
- Environment file permissions (664 → 600)
- Backup log permissions (644 → 640)
- Systemd service User directives
- File permission corrections

**Manual Fixes Required**:
- PostgreSQL authentication configuration
- Docker container non-root user implementation
- Network interface binding restrictions
- Database network binding configuration

### Security Report Review

**View Latest Report**:
```bash
# Find latest security report
ls -lt reports/security-audit-*.txt | head -1

# View report content
cat reports/security-audit-*.txt
```

**Report Contents**:
- Executive summary with issue counts
- Detailed findings by severity
- Security recommendations
- Remediation priority
- Next audit schedule

### Regular Security Audits

**Schedule Weekly Audits**:
```bash
# Add to crontab for weekly audits
crontab -e

# Add line for weekly audit at 3 AM every Sunday
0 3 * * 0 /home/tony/CascadeProjects/chaba/scripts/security-audit.sh
```

**Systemd Timer Alternative**:
```bash
# Create systemd timer for weekly audits
# (implementation similar to backup system)
```

## Troubleshooting

### Issue: Security Audit Fails with Permission Denied

**Symptoms**:
- Audit script fails with permission errors
- Cannot access certain directories
- Log file creation fails

**Causes**:
- Insufficient permissions for audit script
- Log directory not accessible
- System directories restricted

**Solutions**:
```bash
# Check script permissions
ls -la scripts/security-audit.sh

# Ensure script is executable
chmod +x scripts/security-audit.sh

# Check log directory permissions
ls -la logs/

# Create log directory if needed
mkdir -p logs

# Run with sudo if needed (not recommended)
sudo ./scripts/security-audit.sh
```

### Issue: False Positives in Security Audit

**Symptoms**:
- Too many high-risk issues reported
- Library files flagged as sensitive
- Test files marked as security issues

**Causes**:
- False positive filtering not working
- Pattern matching too broad
- New file types not excluded

**Solutions**:
```bash
# Check false positive filtering in security-audit.sh
# Look for node_modules and venv exclusions

# Add additional exclusions if needed
# Edit the sensitive_patterns exclusion logic

# Report false positives to improve filtering
```

### Issue: PostgreSQL Authentication Check Fails

**Symptoms**:
- Database security check fails
- Cannot access pg_hba.conf
- PostgreSQL container not responding

**Causes**:
- PostgreSQL container not running
- Insufficient permissions for container access
- pg_hba.conf location changed

**Solutions**:
```bash
# Check PostgreSQL container status
docker ps | grep postgres

# Test container access
docker exec postgres cat /var/lib/postgresql/data/pg_hba.conf

# Check if security check can access container
docker exec postgres psql -U chaba -d chaba -c "SHOW listen_addresses;"
```

### Issue: Hardening Script Doesn't Fix Issues

**Symptoms**:
- Security hardening runs but issues persist
- File permissions not changed
- Systemd services not updated

**Causes**:
- File ownership conflicts
- Systemd service already has User directive
- File already has correct permissions

**Solutions**:
```bash
# Check file ownership
ls -la .env stacks/web/.env

# Fix ownership if needed
sudo chown tony:tony .env

# Manually fix permissions
chmod 600 .env

# Check systemd service files
grep "User=" systemd/*.service

# Verify hardening script output
./scripts/security-harden.sh 2>&1 | tee hardening-output.log
```

### Issue: Security Report Not Generated

**Symptoms**:
- Audit completes but no report file
- Report directory not accessible
- Report file empty

**Causes**:
- Reports directory not created
- Disk space insufficient
- File write permissions

**Solutions**:
```bash
# Check reports directory
ls -la reports/

# Create reports directory if needed
mkdir -p reports

# Check disk space
df -h

# Manually generate report
./scripts/security-audit.sh > reports/manual-audit.txt
```

## Security Best Practices

### Regular Security Maintenance
1. **Weekly Audits**: Run security-audit.sh weekly
2. **Monthly Hardening**: Run security-harden.sh monthly
3. **Quarterly Reviews**: Review security recommendations
4. **Annual Assessment**: Comprehensive security review

### Credential Management
1. **Environment Variables**: Use environment variables for all secrets
2. **No Hardcoding**: Never hardcode credentials in scripts
3. **Git History**: Remove committed credentials with git-filter-repo
4. **Rotation**: Rotate API keys and passwords regularly

### Container Security
1. **Non-Root Users**: Run containers as non-root users
2. **Minimal Images**: Use minimal base images
3. **Scanning**: Regular vulnerability scanning with Trivy
4. **Updates**: Keep containers and images updated

### Network Security
1. **Interface Binding**: Bind to specific interfaces when possible
2. **Firewall Rules**: Use firewall rules to restrict access
3. **VPN**: Use VPN for remote access
4. **Monitoring**: Monitor network traffic and connections

### Database Security
1. **Authentication**: Use strong authentication (md5, scram-sha-256)
2. **Network Binding**: Restrict to specific IP addresses
3. **Encryption**: Enable SSL/TLS for connections
4. **Backups**: Regular encrypted backups

## Performance Metrics

**Audit Performance**:
- Full audit duration: 30-60 seconds
- Git history scan: 10-20 seconds
- Docker security check: 5-10 seconds
- Network scan: 2-5 seconds
- Report generation: 5-10 seconds

**Hardening Performance**:
- File permission fixes: 5-10 seconds
- Systemd service updates: 5-10 seconds
- Report generation: 5-10 seconds
- Total hardening: 20-30 seconds

**System Impact**:
- CPU usage: <10% during audit
- Memory usage: <50MB
- Disk usage: <1MB for reports
- Network usage: Minimal

## Related Documentation

- **Security Scanning Implementation**: `docs/kb/security-scanning-implementation.md` - Security scanning details
- **SSOT Health**: `docs/ssot/infrastructure/ssot.health.yml` - Security monitoring configuration
- **System Automation**: `docs/kb/system-automation.md` - Systemd timer management

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-13 | Initial creation with comprehensive security audit and hardening | Devin |