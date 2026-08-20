---
category: operations
---

# Recovery Procedures

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

