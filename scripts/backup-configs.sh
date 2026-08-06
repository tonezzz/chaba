#!/bin/bash
#
# Backup Script for Documentation Infrastructure
# Backs up MCP configurations, skills, and critical system configs
#

set -e

# Configuration
BACKUP_DIR="/home/tony/CascadeProjects/chaba/docs/backups/configs"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=30

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

echo "Starting documentation infrastructure backup: $TIMESTAMP"

# Backup MCP configuration
echo "Backing up MCP configuration..."
if [ -f "/home/tony/.config/devin/mcp_config.json" ]; then
    cp /home/tony/.config/devin/mcp_config.json "$BACKUP_DIR/mcp_config_$TIMESTAMP.json"
    echo "✓ MCP configuration backed up"
else
    echo "✗ MCP configuration not found"
fi

# Backup Windsurf MCP configuration (if different)
if [ -f "/home/tony/.config/windsurf/mcp_config.json" ]; then
    cp /home/tony/.config/windsurf/mcp_config.json "$BACKUP_DIR/windsurf_mcp_config_$TIMESTAMP.json"
    echo "✓ Windsurf MCP configuration backed up"
fi

# Backup Devin skills
echo "Backing up Devin skills..."
if [ -d "/home/tony/.config/devin/skills" ]; then
    mkdir -p "$BACKUP_DIR/skills_$TIMESTAMP"
    cp -r /home/tony/.config/devin/skills/* "$BACKUP_DIR/skills_$TIMESTAMP/"
    echo "✓ Devin skills backed up"
else
    echo "✗ Devin skills directory not found"
fi

# Backup Windsurf skills (if different)
if [ -d "/home/tony/.config/windsurf/skills" ]; then
    mkdir -p "$BACKUP_DIR/windsurf_skills_$TIMESTAMP"
    cp -r /home/tony/.config/windsurf/skills/* "$BACKUP_DIR/windsurf_skills_$TIMESTAMP/"
    echo "✓ Windsurf skills backed up"
fi

# Backup global rules
echo "Backing up global rules..."
if [ -f "/home/tony/.codeium/windsurf/memories/global_rules.md" ]; then
    cp /home/tony/.codeium/windsurf/memories/global_rules.md "$BACKUP_DIR/global_rules_$TIMESTAMP.md"
    echo "✓ Global rules backed up"
fi

# Backup project-specific rules
if [ -f "/home/tony/CascadeProjects/chaba/.windsurfrules" ]; then
    cp /home/tony/CascadeProjects/chaba/.windsurfrules "$BACKUP_DIR/project_rules_$TIMESTAMP.md"
    echo "✓ Project rules backed up"
fi

# Create backup manifest
echo "Creating backup manifest..."
cat > "$BACKUP_DIR/manifest_$TIMESTAMP.txt" << EOF
Documentation Infrastructure Backup
Generated: $TIMESTAMP
Hostname: $(hostname)
User: $(whoami)

Backup Contents:
- MCP configuration: mcp_config_$TIMESTAMP.json
- Windsurf MCP: windsurf_mcp_config_$TIMESTAMP.json
- Devin skills: skills_$TIMESTAMP/
- Windsurf skills: windsurf_skills_$TIMESTAMP/
- Global rules: global_rules_$TIMESTAMP.md
- Project rules: project_rules_$TIMESTAMP.md

File Counts:
- MCP config files: $(ls -1 "$BACKUP_DIR"/*_$TIMESTAMP.json 2>/dev/null | wc -l)
- Skill files: $(find "$BACKUP_DIR/skills_$TIMESTAMP" -type f 2>/dev/null | wc -l)
- Rule files: $(ls -1 "$BACKUP_DIR"/*_$TIMESTAMP.md 2>/dev/null | wc -l)
EOF

echo "✓ Backup manifest created"

# Clean up old backups (retention policy)
echo "Cleaning up old backups (older than $RETENTION_DAYS days)..."
find "$BACKUP_DIR" -name "*_$(date +%Y%m%d)*" -mtime +$RETENTION_DAYS -delete 2>/dev/null || true
echo "✓ Old backups cleaned up"

# Create latest symlinks for easy recovery
echo "Creating latest symlinks..."
ln -sf "$BACKUP_DIR/mcp_config_$TIMESTAMP.json" "$BACKUP_DIR/mcp_config_latest.json"
ln -sf "$BACKUP_DIR/skills_$TIMESTAMP" "$BACKUP_DIR/skills_latest"
ln -sf "$BACKUP_DIR/global_rules_$TIMESTAMP.md" "$BACKUP_DIR/global_rules_latest.md"
echo "✓ Latest symlinks created"

echo "Backup completed successfully: $TIMESTAMP"
echo "Backup location: $BACKUP_DIR"
echo "Total size: $(du -sh $BACKUP_DIR | cut -f1)"
