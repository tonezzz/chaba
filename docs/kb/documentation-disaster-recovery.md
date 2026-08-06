---
title: Documentation Disaster Recovery
description: Comprehensive disaster recovery strategy for documentation infrastructure including automated backups, recovery procedures, and verification processes
tags: [disaster-recovery, backup, documentation, MCP, infrastructure]
created: 2026-08-06
updated: 2026-08-06
category: operations
related: [documentation-maintenance-standards.md, ssot.documentation-infrastructure.yml, documentation-search.md]
search_keywords: [disaster recovery, backup, restore, MCP configuration, documentation backup]
---

# Documentation Disaster Recovery

**Abstract**: Comprehensive disaster recovery strategy for Chaba documentation infrastructure with automated daily backups, verification procedures, and recovery processes to ensure documentation search capabilities can be quickly restored after system failures.

## Overview

Documentation disaster recovery strategy protects critical documentation infrastructure including MCP configurations, skills, SSOT files, and search capabilities. The system uses automated daily backups, verification procedures, and documented recovery processes to minimize downtime and data loss.

## Purpose

Ensure documentation infrastructure can be quickly recovered from:
- Complete system loss
- Configuration corruption
- Accidental file deletion
- Repository loss
- MCP server failures

## Critical Infrastructure Components

### Documentation Files
- **Location**: `/home/tony/CascadeProjects/chaba/docs/`
- **Content**: KB entries, SSOT files, architecture docs, assessments
- **Backup Priority**: Critical
- **Recovery Priority**: Critical
- **Backup Method**: Git version control

### MCP Configuration
- **Location**: `/home/tony/.config/devin/mcp_config.json`
- **Content**: MCP server definitions including docs MCP server
- **Backup Priority**: Critical
- **Recovery Priority**: Critical
- **Backup Method**: Automated daily backup script

### Skills Configuration
- **Location**: `/home/tony/.config/devin/skills/`
- **Content**: Devin skills (ssot-search, auto-kb, etc.)
- **Backup Priority**: High
- **Recovery Priority**: High
- **Backup Method**: Automated daily backup script

### SSOT YAML Files
- **Location**: `/home/tony/CascadeProjects/chaba/docs/ssot/`
- **Content**: All SSOT configuration files
- **Backup Priority**: Critical
- **Recovery Priority**: Critical
- **Backup Method**: Git version control

### Documentation Templates
- **Location**: `/home/tony/CascadeProjects/chaba/docs/kb/.template.md`
- **Content**: KB template, SSOT summary templates
- **Backup Priority**: High
- **Recovery Priority**: High
- **Backup Method**: Git version control

## Backup Strategy

### Primary: Git Version Control
- **Scope**: All documentation files in chaba repository
- **Frequency**: Automatic on commit
- **Retention**: Permanent history
- **Recovery**: `git clone` or `git pull`
- **Location**: GitHub repository

### Secondary: Configuration Backup Script
- **Scope**: MCP configs, skills, rules
- **Frequency**: Daily at 3 AM via cron
- **Retention**: 30 days
- **Recovery**: Manual restore from backup
- **Location**: `docs/backups/configs/`

### Tertiary: System-Level Backup
- **Scope**: Full system including `/home/tony/.config/devin/`
- **Frequency**: Weekly
- **Retention**: 4 weeks
- **Recovery**: System restore from snapshot
- **Location**: Timeshift or similar

## Automation Scripts

### Backup Script: `scripts/backup-configs.sh`

**Purpose**: Automated daily backup of MCP configurations and skills

**What it backs up:**
- MCP configuration (`mcp_config.json`)
- Windsurf MCP configuration
- Devin skills directory
- Windsurf skills directory
- Global rules (`global_rules.md`)
- Project rules (`.windsurfrules`)

**Features:**
- Timestamped backups
- Automatic cleanup of old backups (30-day retention)
- Creates latest symlinks for easy recovery
- Generates backup manifest
- Size reporting

**Usage:**
```bash
./scripts/backup-configs.sh
```

**Scheduled**: Daily at 3 AM via cron

### Verification Script: `scripts/verify-docs.sh`

**Purpose**: Verify documentation integrity and search functionality

**What it checks:**
- Documentation file count (minimum 100 files expected)
- Critical directories exist (kb, ssot, architecture, etc.)
- KB template exists
- SSOT index exists
- Search index exists
- SSOT summaries exist
- MCP configuration exists
- Backup directory status
- File integrity (no empty files)
- Recent documentation activity
- Git repository status

**Usage:**
```bash
./scripts/verify-docs.sh
```

**Scheduled**: Weekly on Sunday at 2 AM via cron

### Recovery Script: `scripts/recover-configs.sh`

**Purpose**: Restore MCP configurations and skills from backup

**What it restores:**
- MCP configuration
- Windsurf MCP configuration
- Devin skills
- Windsurf skills
- Global rules
- Project rules

**Features:**
- Creates restore point before recovery
- Supports specific timestamp or "latest" backup
- Verifies backup files exist before restore
- Provides clear next steps after recovery

**Usage:**
```bash
# Restore from latest backup
./scripts/recover-configs.sh

# Restore from specific timestamp
./scripts/recover-configs.sh 20260806_030000
```

### Automation Setup: `scripts/setup-automation-cron.sh`

**Purpose**: Configure cron jobs for automated backups and verification

**What it sets up:**
- Daily backup at 3 AM
- Weekly verification on Sunday at 2 AM
- Log file configuration
- Crontab management

**Usage:**
```bash
./scripts/setup-automation-cron.sh
```

## Recovery Procedures

### Complete System Loss

**Scenario**: Total system failure requiring full restore

**Recovery Steps**:
1. Restore system from Timeshift snapshot
2. Clone chaba repository from GitHub
3. Restore MCP configs: `./scripts/recover-configs.sh`
4. Restart Devin Desktop
5. Verify MCP servers: `mcp_list_servers`
6. Test search functionality: `mcp_call_tool docs search_docs "test" 3`

**Estimated Recovery Time**: 30-60 minutes
**Data Loss Potential**: Minimal (daily backups)

### Documentation Corruption

**Scenario**: Documentation files corrupted or accidentally deleted

**Recovery Steps**:
1. Git checkout clean version: `git checkout -- .`
2. Verify file integrity: `./scripts/verify-docs.sh`
3. Test search functionality
4. Commit restored version if needed

**Estimated Recovery Time**: 5-10 minutes
**Data Loss Potential**: Minimal (git history)

### MCP Configuration Loss

**Scenario**: MCP config file corrupted or deleted

**Recovery Steps**:
1. Restore from daily backup: `./scripts/recover-configs.sh`
2. Restart Devin Desktop
3. Verify MCP servers: `mcp_list_servers`
4. Test docs MCP server: `mcp_call_tool docs list_sections`

**Estimated Recovery Time**: 5-10 minutes
**Data Loss Potential**: Minimal (daily backups)

### Repository Loss

**Scenario**: GitHub repository lost or corrupted

**Recovery Steps**:
1. Restore from local system backup
2. Create new GitHub repository
3. Push restored content
4. Update remote URLs
5. Verify all branches and tags

**Estimated Recovery Time**: 20-30 minutes
**Data Loss Potential**: Minimal (local backups)

## Verification Procedures

### Documentation Integrity Check

**Command**: `./scripts/verify-docs.sh`

**What it verifies**:
- File count meets minimum (100+ files)
- Critical directories exist
- Template files present
- SSOT summaries available
- MCP configuration exists
- No empty or corrupted files
- Git repository status

**Frequency**: Weekly automated, manual as needed

### MCP Server Verification

**Command**: `mcp_list_servers`

**Expected Servers**: docs, github, yomi, postgres, mcp-gpu, mcp-llama

**Frequency**: Daily automated check, manual as needed

### Search Functionality Test

**Command**: `mcp_call_tool docs search_docs "GPU memory" 3`

**Expected Result**: 3 relevant search results

**Frequency**: Weekly automated, manual as needed

### Configuration Consistency Check

**Command**: `diff ~/.config/devin/mcp_config.json docs/backups/configs/mcp_config.json`

**Expected Result**: No differences or documented changes

**Frequency**: Weekly automated, manual as needed

## Backup Locations

### Primary Storage
- **Git Repository**: GitHub (remote)
- **Local Repository**: `/home/tony/CascadeProjects/chaba/.git`

### Configuration Backups
- **Location**: `/home/tony/CascadeProjects/chaba/docs/backups/configs/`
- **Retention**: 30 days
- **Contents**: MCP configs, skills, rules

### Restore Points
- **Location**: `/home/tony/CascadeProjects/chaba/docs/backups/configs/restore_points/`
- **Created**: Before each recovery operation
- **Retention**: Manual cleanup

### Logs
- **Backup Log**: `docs/backups/backup.log`
- **Verification Log**: `docs/backups/verify.log`

## SSOT Configuration

The disaster recovery strategy is documented in SSOT for single source of truth:

**SSOT File**: `docs/ssot/ssot.documentation-infrastructure.yml`

**Contains**:
- Critical infrastructure components
- Backup strategy details
- Recovery procedures
- Automation configuration
- Verification procedures
- Disaster recovery scenarios
- Contact information

## Maintenance

### Monthly Tasks
- Review backup logs for errors
- Test recovery procedure on non-production system
- Verify retention policy compliance
- Update contact information if needed

### Quarterly Tasks
- Review and update disaster recovery documentation
- Test complete disaster recovery scenario
- Verify backup storage capacity
- Update automation scripts if needed

### Annual Tasks
- Complete disaster recovery drill
- Review and update backup strategy
- Verify all contact information
- Update SSOT configuration

## Troubleshooting

### Backup Script Fails

**Symptoms**: Backup script returns error, incomplete backup

**Solutions**:
- Check disk space availability
- Verify permissions on backup directory
- Check MCP configuration file exists
- Review backup logs for specific errors

### Verification Script Fails

**Symptoms**: Verification returns errors, missing files

**Solutions**:
- Check documentation directory exists
- Verify Git repository status
- Run backup script to ensure fresh backup
- Review verification logs for specific failures

### Recovery Script Fails

**Symptoms**: Recovery incomplete, configuration not restored

**Solutions**:
- Verify backup files exist
- Check permissions on target directories
- Use restore point to revert if needed
- Manually restore individual components

### MCP Servers Not Available After Recovery

**Symptoms**: `mcp_list_servers` missing expected servers

**Solutions**:
- Restart Devin Desktop
- Verify MCP configuration file syntax
- Check docs MCP server can rebuild index
- Review Devin Desktop logs for errors

## Related Documentation

- **Documentation Infrastructure SSOT**: `docs/ssot/ssot.documentation-infrastructure.yml` - Complete SSOT configuration
- **Documentation Maintenance Standards**: `docs/kb/documentation-maintenance-standards.md` - Maintenance procedures
- **Documentation Search**: `docs/kb/documentation-search.md` - Search methods and MCP integration
- **SSOT Index**: `docs/ssot/ssot.index.yml` - Master SSOT file index

## Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-06 | Initial disaster recovery documentation | devin |
