---
category: operations
---

# Critical Infrastructure Components

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

