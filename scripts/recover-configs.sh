#!/bin/bash
#
# Recovery Script for Documentation Infrastructure
# Restores MCP configurations, skills, and critical system configs from backup
#

set -e

# Configuration
BACKUP_DIR="/home/tony/CascadeProjects/chaba-tony-dell/docs/backups/configs"
TIMESTAMP=${1:-latest}

echo "Starting documentation infrastructure recovery: $TIMESTAMP"
echo "=========================================="

# Check backup directory exists
if [ ! -d "$BACKUP_DIR" ]; then
    echo "✗ Backup directory not found: $BACKUP_DIR"
    echo "Run backup script first: ./scripts/backup-configs.sh"
    exit 1
fi

# Determine which backup to use
if [ "$TIMESTAMP" = "latest" ]; then
    MCP_CONFIG="$BACKUP_DIR/mcp_config_latest.json"
    SKILLS_DIR="$BACKUP_DIR/skills_latest"
    GLOBAL_RULES="$BACKUP_DIR/global_rules_latest.md"
    echo "Using latest backup"
else
    MCP_CONFIG="$BACKUP_DIR/mcp_config_$TIMESTAMP.json"
    SKILLS_DIR="$BACKUP_DIR/skills_$TIMESTAMP"
    GLOBAL_RULES="$BACKUP_DIR/global_rules_$TIMESTAMP.md"
    echo "Using backup from: $TIMESTAMP"
fi

# Verify backup files exist
echo "Verifying backup files..."
if [ ! -f "$MCP_CONFIG" ]; then
    echo "✗ MCP configuration backup not found: $MCP_CONFIG"
    exit 1
fi
echo "✓ MCP configuration backup found"

if [ ! -d "$SKILLS_DIR" ]; then
    echo "✗ Skills backup not found: $SKILLS_DIR"
    exit 1
fi
echo "✓ Skills backup found"

if [ ! -f "$GLOBAL_RULES" ]; then
    echo "⚠ Global rules backup not found: $GLOBAL_RULES (skipping)"
else
    echo "✓ Global rules backup found"
fi

# Create restore point (backup current configs)
echo "Creating restore point..."
CURRENT_TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR/restore_points/$CURRENT_TIMESTAMP"

if [ -f "/home/tony/.config/devin/mcp_config.json" ]; then
    cp /home/tony/.config/devin/mcp_config.json "$BACKUP_DIR/restore_points/$CURRENT_TIMESTAMP/mcp_config_before_restore.json"
    echo "✓ Current MCP config backed up"
fi

if [ -d "/home/tony/.config/devin/skills" ]; then
    cp -r /home/tony/.config/devin/skills "$BACKUP_DIR/restore_points/$CURRENT_TIMESTAMP/skills_before_restore"
    echo "✓ Current skills backed up"
fi

# Restore MCP configuration
echo "Restoring MCP configuration..."
cp "$MCP_CONFIG" /home/tony/.config/devin/mcp_config.json
echo "✓ MCP configuration restored"

# Restore Windsurf MCP configuration if exists
WINDSURF_MCP="$BACKUP_DIR/windsurf_mcp_config_$TIMESTAMP.json"
if [ -f "$WINDSURF_MCP" ]; then
    cp "$WINDSURF_MCP" /home/tony/.config/windsurf/mcp_config.json
    echo "✓ Windsurf MCP configuration restored"
else
    echo "⚠ Windsurf MCP backup not found (skipping)"
fi

# Restore Devin skills
echo "Restoring Devin skills..."
mkdir -p /home/tony/.config/devin/skills
cp -r "$SKILLS_DIR"/* /home/tony/.config/devin/skills/
echo "✓ Devin skills restored"

# Restore Windsurf skills if exists
WINDSURF_SKILLS="$BACKUP_DIR/windsurf_skills_$TIMESTAMP"
if [ -d "$WINDSURF_SKILLS" ]; then
    mkdir -p /home/tony/.config/windsurf/skills
    cp -r "$WINDSURF_SKILLS"/* /home/tony/.config/windsurf/skills/
    echo "✓ Windsurf skills restored"
else
    echo "⚠ Windsurf skills backup not found (skipping)"
fi

# Restore global rules if exists
if [ -f "$GLOBAL_RULES" ]; then
    mkdir -p /home/tony/.codeium/windsurf/memories
    cp "$GLOBAL_RULES" /home/tony/.codeium/windsurf/memories/global_rules.md
    echo "✓ Global rules restored"
fi

# Restore project rules if exists
PROJECT_RULES="$BACKUP_DIR/project_rules_$TIMESTAMP.md"
if [ -f "$PROJECT_RULES" ]; then
    cp "$PROJECT_RULES" /home/tony/CascadeProjects/chaba-tony-dell/.windsurfrules
    echo "✓ Project rules restored"
else
    echo "⚠ Project rules backup not found (skipping)"
fi

echo "=========================================="
echo "Recovery completed successfully"
echo ""
echo "Restore point created: $BACKUP_DIR/restore_points/$CURRENT_TIMESTAMP"
echo ""
echo "Next steps:"
echo "1. Restart Devin Desktop to reload MCP configuration"
echo "2. Verify MCP servers: mcp_list_servers"
echo "3. Test search functionality: mcp_call_tool docs search_docs 'test' 3"
echo "4. If issues occur, restore from restore point:"
echo "   cp $BACKUP_DIR/restore_points/$CURRENT_TIMESTAMP/mcp_config_before_restore.json ~/.config/devin/mcp_config.json"
