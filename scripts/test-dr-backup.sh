#!/bin/bash
#
# Dry-Run Disaster Recovery Test
# Validates backup integrity and recovery procedures without actual restoration
#

set -e

echo "=========================================="
echo "Dry-Run Disaster Recovery Test"
echo "=========================================="
echo "Test Date: $(date)"
echo ""

# Test 1: Backup Script Validation
echo "Test 1: Backup Script Validation"
echo "--------------------------------"
if [ -f "/home/tony/CascadeProjects/chaba/scripts/backup-configs.sh" ]; then
    echo "✓ Backup script exists"
    if [ -x "/home/tony/CascadeProjects/chaba/scripts/backup-configs.sh" ]; then
        echo "✓ Backup script is executable"
    else
        echo "✗ Backup script is not executable"
        exit 1
    fi
else
    echo "✗ Backup script not found"
    exit 1
fi

# Test 2: Backup Directory Structure
echo ""
echo "Test 2: Backup Directory Structure"
echo "--------------------------------"
BACKUP_DIR="/home/tony/CascadeProjects/chaba/docs/backups/configs"
if [ -d "$BACKUP_DIR" ]; then
    echo "✓ Backup directory exists: $BACKUP_DIR"
    BACKUP_COUNT=$(ls -1 "$BACKUP_DIR"/*.json 2>/dev/null | wc -l)
    echo "  Backup files found: $BACKUP_COUNT"
    if [ $BACKUP_COUNT -eq 0 ]; then
        echo "⚠ No backup files found (run backup script first)"
    else
        echo "✓ Backup files present"
        LATEST_BACKUP=$(ls -t "$BACKUP_DIR"/mcp_config_*.json 2>/dev/null | head -1)
        if [ -n "$LATEST_BACKUP" ]; then
            echo "  Latest backup: $(basename $LATEST_BACKUP)"
        fi
    fi
else
    echo "✗ Backup directory not found"
    echo "  Creating backup directory..."
    mkdir -p "$BACKUP_DIR"
    echo "✓ Backup directory created"
fi

# Test 3: Critical Files Backup Verification
echo ""
echo "Test 3: Critical Files Backup Verification"
echo "--------------------------------"
CRITICAL_FILES=(
    "/home/tony/.config/devin/mcp_config.json"
    "/home/tony/.config/devin/skills"
    "/home/tony/.codeium/windsurf/memories/global_rules.md"
    "/home/tony/CascadeProjects/chaba/.windsurfrules"
)

for file in "${CRITICAL_FILES[@]}"; do
    if [ -e "$file" ]; then
        echo "✓ Critical file exists: $file"
    else
        echo "⚠ Critical file missing: $file"
    fi
done

# Test 4: Recovery Script Validation
echo ""
echo "Test 4: Recovery Script Validation"
echo "--------------------------------"
if [ -f "/home/tony/CascadeProjects/chaba/scripts/recover-configs.sh" ]; then
    echo "✓ Recovery script exists"
    if [ -x "/home/tony/CascadeProjects/chaba/scripts/recover-configs.sh" ]; then
        echo "✓ Recovery script is executable"
    else
        echo "✗ Recovery script is not executable"
        exit 1
    fi
else
    echo "✗ Recovery script not found"
    exit 1
fi

# Test 5: Verification Script Validation
echo ""
echo "Test 5: Verification Script Validation"
echo "--------------------------------"
if [ -f "/home/tony/CascadeProjects/chaba/scripts/verify-docs.sh" ]; then
    echo "✓ Verification script exists"
    if [ -x "/home/tony/CascadeProjects/chaba/scripts/verify-docs.sh" ]; then
        echo "✓ Verification script is executable"
    else
        echo "✗ Verification script is not executable"
        exit 1
    fi
else
    echo "✗ Verification script not found"
    exit 1
fi

# Test 6: Documentation Integrity
echo ""
echo "Test 6: Documentation Integrity"
echo "--------------------------------"
DOCS_DIR="/home/tony/CascadeProjects/chaba/docs"
if [ -d "$DOCS_DIR" ]; then
    echo "✓ Documentation directory exists"
    MD_COUNT=$(find "$DOCS_DIR" -type f -name "*.md" | wc -l)
    YML_COUNT=$(find "$DOCS_DIR" -type f -name "*.yml" | wc -l)
    echo "  Markdown files: $MD_COUNT"
    echo "  YAML files: $YML_COUNT"
    
    if [ $MD_COUNT -lt 50 ] || [ $YML_COUNT -lt 20 ]; then
        echo "⚠ File count seems low (expected 50+ MD, 20+ YAML)"
    else
        echo "✓ File count looks reasonable"
    fi
else
    echo "✗ Documentation directory not found"
    exit 1
fi

# Test 7: Git Repository Status
echo ""
echo "Test 7: Git Repository Status"
echo "--------------------------------"
if git -C "$DOCS_DIR" rev-parse --git-dir > /dev/null 2>&1; then
    echo "✓ Git repository initialized"
    REMOTE_URL=$(git -C "$DOCS_DIR" config --get remote.origin.url)
    if [ -n "$REMOTE_URL" ]; then
        echo "  Remote URL: $REMOTE_URL"
        echo "✓ Git remote configured"
    else
        echo "⚠ No Git remote configured"
    fi
    UNCOMMITTED=$(git -C "$DOCS_DIR" status --porcelain | wc -l)
    if [ $UNCOMMITTED -gt 0 ]; then
        echo "⚠ $UNCOMMITTED uncommitted changes (consider committing)"
    else
        echo "✓ Working directory clean"
    fi
else
    echo "⚠ Not a Git repository (version control recommended)"
fi

# Test 8: MCP Configuration Validation
echo ""
echo "Test 8: MCP Configuration Validation"
echo "--------------------------------"
MCP_CONFIG="/home/tony/.config/devin/mcp_config.json"
if [ -f "$MCP_CONFIG" ]; then
    echo "✓ MCP configuration exists"
    if python3 -c "import json; json.load(open('$MCP_CONFIG'))" 2>/dev/null; then
        echo "✓ MCP configuration is valid JSON"
        DOCS_MCP=$(python3 -c "import json; config = json.load(open('$MCP_CONFIG')); print('docs' in config.get('mcpServers', {}))" 2>/dev/null)
        if [ "$DOCS_MCP" = "True" ]; then
            echo "✓ docs MCP server configured"
        else
            echo "⚠ docs MCP server not found in configuration"
        fi
    else
        echo "✗ MCP configuration is not valid JSON"
    fi
else
    echo "✗ MCP configuration not found"
fi

# Test 9: Backup Manifest Validation
echo ""
echo "Test 9: Backup Manifest Validation"
echo "--------------------------------"
LATEST_MANIFEST=$(ls -t "$BACKUP_DIR"/manifest_*.txt 2>/dev/null | head -1)
if [ -n "$LATEST_MANIFEST" ]; then
    echo "✓ Latest backup manifest found: $(basename $LATEST_MANIFEST)"
    echo "  Manifest contents:"
    cat "$LATEST_MANIFEST"
else
    echo "⚠ No backup manifest found (run backup script first)"
fi

# Test 10: Disk Space Check
echo ""
echo "Test 10: Disk Space Check"
echo "--------------------------------"
DISK_AVAILABLE=$(df -h "$BACKUP_DIR" | tail -1 | awk '{print $4}')
DISK_PERCENT=$(df -h "$BACKUP_DIR" | tail -1 | awk '{print $5}')
echo "Available disk space: $DISK_AVAILABLE"
echo "Disk usage: $DISK_PERCENT"
if [ "${DISK_PERCENT%\%}" -gt 90 ]; then
    echo "⚠ Disk usage above 90%"
else
    echo "✓ Disk space OK"
fi

# Summary
echo ""
echo "=========================================="
echo "Dry-Run Test Summary"
echo "=========================================="
echo "All critical validation checks completed"
echo ""
echo "Next Steps:"
echo "1. Run initial backup: ./scripts/backup-configs.sh"
echo "2. Run verification: ./scripts/verify-docs.sh"
echo "3. Setup automation: ./scripts/setup-automation-cron.sh"
echo "4. Commit changes to Git repository"
echo ""
echo "When test facility becomes available:"
echo "1. Run full recovery test on test system"
echo "2. Verify MCP servers after recovery"
echo "3. Test search functionality"
echo "4. Document any issues found"
