#!/bin/bash
# Generate comprehensive SSOT configuration status report

set -e

SSOT_DIR="/home/tony/CascadeProjects/chaba-tony-dell/docs/ssot"
REPORT_FILE="/tmp/ssot-config-status-report.txt"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

echo "=========================================="
echo "SSOT Configuration Status Report"
echo "Generated: $TIMESTAMP"
echo "=========================================="
echo ""

# Counters
TOTAL_FILES=0
VALID_FILES=0
INVALID_FILES=0
WARNINGS=0
DRIFT_COUNT=0

# Function to check for configuration drift
check_drift() {
    local source_file="$1"
    local filename=$(basename "$source_file")
    local served_file="/home/tony/CascadeProjects/chaba-tony-dell/stacks/web/public/$filename"
    local public_file="/home/tony/CascadeProjects/chaba-tony-dell/public/docs/overview/$filename"
    
    local has_drift=false
    
    if [ -f "$served_file" ]; then
        if ! diff -q "$source_file" "$served_file" >/dev/null 2>&1; then
            echo "  DRIFT: Differs from served copy: $served_file"
            has_drift=true
            DRIFT_COUNT=$((DRIFT_COUNT + 1))
        fi
    fi
    
    if [ -f "$public_file" ]; then
        if ! diff -q "$source_file" "$public_file" >/dev/null 2>&1; then
            echo "  DRIFT: Differs from public copy: $public_file"
            has_drift=true
            DRIFT_COUNT=$((DRIFT_COUNT + 1))
        fi
    fi
    
    $has_drift
}

# MCP Configuration Status
echo "1. MCP Configuration Status"
echo "----------------------------"
if [ -f "$SSOT_DIR/ssot.devin.tools.yml" ]; then
    echo "✓ MCP configuration file exists: ssot.devin.tools.yml"
    
    # Count MCP servers
    mcp_count=$(grep -E "^[[:space:]]*[a-z-]+:" "$SSOT_DIR/ssot.devin.tools.yml" | grep -v "^mcp-conf:" | grep -v "^--$" | wc -l)
    echo "  MCP servers defined: $mcp_count"
    
    # List MCP servers
    echo "  MCP servers:"
    grep -A 1 "^mcp:" "$SSOT_DIR/ssot.devin.tools.yml" | grep -v "^mcp:" | grep -v "^--$" | sed 's/^/    - /'
    
    # Check mcp-conf
    if grep -q "^mcp-conf:" "$SSOT_DIR/ssot.devin.tools.yml"; then
        echo "✓ MCP configuration section exists"
        mcp_conf_count=$(grep -A 1 "^- name:" "$SSOT_DIR/ssot.devin.tools.yml" | grep "name:" | wc -l)
        echo "  MCP server configurations: $mcp_conf_count"
    else
        echo "✗ No mcp-conf section found"
        INVALID_FILES=$((INVALID_FILES + 1))
    fi
else
    echo "✗ MCP configuration file missing"
    INVALID_FILES=$((INVALID_FILES + 1))
fi
echo ""

# SSOT File Validation
echo "2. SSOT File Validation"
echo "-----------------------"
for file in "$SSOT_DIR"/**/*.yml; do
    if [[ "$file" =~ template\.yml$ ]]; then
        continue
    fi
    
    TOTAL_FILES=$((TOTAL_FILES + 1))
    filename=$(basename "$file")
    
    # Check YAML syntax
    if python3 -c "import yaml; yaml.safe_load(open('$file'))" 2>/dev/null; then
        VALID_FILES=$((VALID_FILES + 1))
        echo "✓ $filename"
        
        # Check for drift
        check_drift "$file" || true
    else
        INVALID_FILES=$((INVALID_FILES + 1))
        echo "✗ $filename (invalid YAML)"
    fi
done
echo ""

# Wrapper Script Status
echo "3. Wrapper Script Status"
echo "------------------------"
wrapper_count=0
missing_count=0
not_executable_count=0

for script in /home/tony/CascadeProjects/chaba-tony-dell/.windsurf/run-*.sh; do
    if [ -f "$script" ]; then
        wrapper_count=$((wrapper_count + 1))
        script_name=$(basename "$script")
        
        if [ -x "$script" ]; then
            echo "✓ $script_name (executable)"
        else
            echo "⚠ $script_name (not executable)"
            not_executable_count=$((not_executable_count + 1))
        fi
    fi
done
echo ""

# Configuration Drift Summary
echo "4. Configuration Drift Summary"
echo "------------------------------"
echo "Files with configuration drift: $DRIFT_COUNT"
if [ $DRIFT_COUNT -gt 0 ]; then
    echo "⚠️  Action needed: Sync source files with served/public copies"
    echo "   Run: cp docs/ssot/*.yml stacks/web/public/"
    echo "   Run: cp docs/ssot/**/*.yml public/docs/overview/"
else
    echo "✓ No configuration drift detected"
fi
echo ""

# Overall Summary
echo "=========================================="
echo "Summary"
echo "=========================================="
echo "Total SSOT files: $TOTAL_FILES"
echo "Valid files: $VALID_FILES"
echo "Invalid files: $INVALID_FILES"
echo "Wrapper scripts: $wrapper_count"
echo "Non-executable wrappers: $not_executable_count"
echo "Configuration drift: $DRIFT_COUNT files"
echo ""

# Recommendations
echo "=========================================="
echo "Recommendations"
echo "=========================================="

if [ $INVALID_FILES -gt 0 ]; then
    echo "❌ Fix invalid SSOT files before proceeding"
    echo "   Run: bash scripts/validate-configs.sh"
fi

if [ $not_executable_count -gt 0 ]; then
    echo "⚠️  Make wrapper scripts executable:"
    echo "   Run: chmod +x /home/tony/CascadeProjects/chaba-tony-dell/.windsurf/run-*.sh"
fi

if [ $DRIFT_COUNT -gt 0 ]; then
    echo "⚠️  Sync configuration files to eliminate drift"
    echo "   Run: rsync -av docs/ssot/ stacks/web/public/"
    echo "   Run: rsync -av docs/ssot/ public/docs/overview/"
fi

if [ $INVALID_FILES -eq 0 ] && [ $not_executable_count -eq 0 ] && [ $DRIFT_COUNT -eq 0 ]; then
    echo "✅ All configurations are healthy"
    echo "   No immediate action required"
fi

echo ""
echo "=========================================="
echo "Report Complete"
echo "=========================================="
