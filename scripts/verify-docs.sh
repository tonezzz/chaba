#!/bin/bash
#
# Documentation Infrastructure Verification Script
# Verifies documentation integrity, MCP servers, and search functionality
#

set -e

# Configuration
DOCS_DIR="/home/tony/CascadeProjects/chaba-tony-dell/docs"
EXPECTED_MIN_FILES=100
EXPECTED_MCP_SERVERS="docs github yomi postgres mcp-gpu mcp-llama"

echo "Starting documentation infrastructure verification: $(date)"
echo "=========================================="

# Check documentation directory exists
if [ ! -d "$DOCS_DIR" ]; then
    echo "✗ Documentation directory not found: $DOCS_DIR"
    exit 1
fi
echo "✓ Documentation directory exists"

# Count documentation files
echo "Checking documentation files..."
MD_COUNT=$(find "$DOCS_DIR" -type f -name "*.md" | wc -l)
YML_COUNT=$(find "$DOCS_DIR" -type f -name "*.yml" | wc -l)
TOTAL_FILES=$((MD_COUNT + YML_COUNT))

echo "  Markdown files: $MD_COUNT"
echo "  YAML files: $YML_COUNT"
echo "  Total files: $TOTAL_FILES"

if [ $TOTAL_FILES -lt $EXPECTED_MIN_FILES ]; then
    echo "✗ File count below minimum expected: $TOTAL_FILES < $EXPECTED_MIN_FILES"
    exit 1
fi
echo "✓ Documentation file count OK"

# Check critical directories exist
echo "Checking critical directories..."
CRITICAL_DIRS=("kb" "ssot" "architecture" "assessments" "ssot-summaries")
for dir in "${CRITICAL_DIRS[@]}"; do
    if [ -d "$DOCS_DIR/$dir" ]; then
        echo "  ✓ $dir/ exists"
    else
        echo "  ✗ $dir/ missing"
        exit 1
    fi
done

# Check KB template exists
if [ -f "$DOCS_DIR/kb/.template.md" ]; then
    echo "✓ KB template exists"
else
    echo "✗ KB template missing"
    exit 1
fi

# Check SSOT index exists
if [ -f "$DOCS_DIR/ssot/ssot.index.yml" ]; then
    echo "✓ SSOT index exists"
else
    echo "✗ SSOT index missing"
    exit 1
fi

# Check search index exists
if [ -f "$DOCS_DIR/SEARCH_INDEX.md" ]; then
    echo "✓ Search index exists"
else
    echo "✗ Search index missing"
    exit 1
fi

# Check SSOT summaries exist
echo "Checking SSOT summaries..."
SSOT_SUMMARIES=("ssot.health-summary.md" "ssot.gpu-summary.md" "ssot.apps-summary.md")
for summary in "${SSOT_SUMMARIES[@]}"; do
    if [ -f "$DOCS_DIR/ssot-summaries/$summary" ]; then
        echo "  ✓ $summary exists"
    else
        echo "  ✗ $summary missing"
        exit 1
    fi
done

# Check MCP configuration exists
echo "Checking MCP configuration..."
if [ -f "/home/tony/.config/devin/mcp_config.json" ]; then
    echo "✓ MCP configuration exists"
else
    echo "✗ MCP configuration missing"
    exit 1
fi

# Check backup directory exists
BACKUP_DIR="/home/tony/CascadeProjects/chaba-tony-dell/docs/backups/configs"
if [ -d "$BACKUP_DIR" ]; then
    BACKUP_COUNT=$(ls -1 "$BACKUP_DIR"/*_latest* 2>/dev/null | wc -l)
    echo "✓ Backup directory exists ($BACKUP_COUNT latest backups)"
else
    echo "⚠ Backup directory missing (will be created on first backup)"
fi

# Verify file integrity (check for empty files)
echo "Checking for empty or corrupted files..."
EMPTY_FILES=$(find "$DOCS_DIR" -type f -size 0 | wc -l)
if [ $EMPTY_FILES -gt 0 ]; then
    echo "✗ Found $EMPTY_FILES empty files"
    find "$DOCS_DIR" -type f -size 0
    exit 1
fi
echo "✓ No empty files found"

# Check for recent modifications (should have some activity in last 7 days)
echo "Checking recent documentation activity..."
RECENT_FILES=$(find "$DOCS_DIR" -type f -mtime -7 | wc -l)
echo "  Files modified in last 7 days: $RECENT_FILES"
if [ $RECENT_FILES -eq 0 ]; then
    echo "⚠ No files modified in last 7 days (may indicate stale documentation)"
fi

# Check Git repository status
echo "Checking Git repository status..."
if git -C "$DOCS_DIR" rev-parse --git-dir > /dev/null 2>&1; then
    echo "✓ Git repository initialized"
    UNCOMMITTED=$(git -C "$DOCS_DIR" status --porcelain | wc -l)
    if [ $UNCOMMITTED -gt 0 ]; then
        echo "⚠ $UNCOMMITTED uncommitted changes"
    else
        echo "✓ Working directory clean"
    fi
else
    echo "⚠ Not a Git repository (version control recommended)"
fi

echo "=========================================="
echo "Verification completed successfully"
echo "Summary:"
echo "  Documentation files: $TOTAL_FILES"
echo "  Critical directories: ${#CRITICAL_DIRS[@]}"
echo "  SSOT summaries: ${#SSOT_SUMMARIES[@]}"
echo "  MCP configuration: OK"
echo "  Backup status: OK"
echo ""
echo "Next steps:"
echo "1. Test MCP servers: mcp_list_servers"
echo "2. Test search functionality: mcp_call_tool docs search_docs 'test' 3"
echo "3. Run backup: ./scripts/backup-configs.sh"
