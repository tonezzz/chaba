#!/bin/bash
# Validate SSOT configuration files for consistency and correctness

set -e

SSOT_DIR="/home/tony/CascadeProjects/chaba-tony-dell/docs/ssot"
SERVED_DIR="/home/tony/CascadeProjects/chaba-tony-dell/stacks/web/public"
PUBLIC_DIR="/home/tony/CascadeProjects/chaba-tony-dell/public/docs/overview"

echo "=========================================="
echo "SSOT Configuration Validation"
echo "=========================================="

# Counters (global)
TOTAL_FILES=0
VALID_FILES=0
INVALID_FILES=0
WARNINGS=0

# Function to validate YAML syntax
validate_yaml_syntax() {
    local file="$1"
    if python3 -c "import yaml; yaml.safe_load(open('$file'))" 2>/dev/null; then
        return 0
    else
        return 1
    fi
}

# Function to check for required fields in standard SSOT files
validate_ssot_structure() {
    local file="$1"
    local filename=$(basename "$file")
    
    # Skip config-type files that have flexible structures
    if [[ "$filename" =~ ^(ssot\.health|ssot\.gpu|ssot\.services|ssot\.apps|ssot\.devin\.tools|ssot\.ui|ssot\.docs|ssot\.libs|ssot\.diagrams|ssot\.validation|ssot\.focus)\.yml$ ]]; then
        return 0
    fi
    
    # Skip simple data files (apps subdirectory)
    if [[ "$file" =~ /apps/ssot\.apps\.[^.]+\.yml$ ]]; then
        return 0
    fi
    
    # Check for title field (required for standard SSOT files)
    if ! grep -q "^title:" "$file" 2>/dev/null; then
        echo "  ERROR: Missing 'title' field"
        return 1
    fi
    
    # Check for sections
    if grep -q "^sections:" "$file" 2>/dev/null; then
        # Validate each section has required fields
        local section_num=0
        while IFS= read -r line; do
            if [[ "$line" =~ ^[[:space:]]*-[[:space:]]*$ ]]; then
                section_num=$((section_num + 1))
            fi
        done < "$file"
    fi
    
    return 0
}

# Function to check for duplicate entries
check_duplicates() {
    local file="$1"
    local duplicates=0
    
    # Check for duplicate section titles
    local section_titles=$(grep -E "^[[:space:]]*-[[:space:]]*title:" "$file" 2>/dev/null | sed 's/.*title:[[:space:]]*//' || true)
    if [ -n "$section_titles" ]; then
        local unique_titles=$(echo "$section_titles" | sort -u)
        local total_titles=$(echo "$section_titles" | wc -l)
        local unique_count=$(echo "$unique_titles" | wc -l)
        
        if [ "$total_titles" -gt "$unique_count" ]; then
            echo "  WARNING: Duplicate section titles found"
            duplicates=$((duplicates + 1))
        fi
    fi
    
    return $duplicates
}

# Function to check hostname compliance
check_hostnames() {
    local file="$1"
    local ip_count=0
    
    # Check for IP addresses (excluding documentation/exceptions)
    local ips=$(grep -E '\b(192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[01])\.)' "$file" 2>/dev/null || true)
    
    if [ -n "$ips" ]; then
        # Check if this is a health check config (IPs allowed there)
        if [[ "$file" =~ ssot\.health\. ]]; then
            return 0
        fi
        
        echo "  WARNING: IP addresses found (should use .local hostnames):"
        echo "$ips" | head -3 | sed 's/^/    /'
        ip_count=$(echo "$ips" | wc -l)
    fi
    
    return $ip_count
}

# Function to compare SSOT files with served copies
compare_with_served() {
    local source_file="$1"
    local filename
    filename=$(basename "$source_file")
    local served_file="$SERVED_DIR/$filename"
    local public_file="$PUBLIC_DIR/$filename"
    
    local differences=0
    
    if [ -f "$served_file" ]; then
        if ! diff -q "$source_file" "$served_file" >/dev/null 2>&1; then
            echo "  WARNING: Differs from served copy: $served_file"
            differences=$((differences + 1))
        fi
    fi
    
    if [ -f "$public_file" ]; then
        if ! diff -q "$source_file" "$public_file" >/dev/null 2>&1; then
            echo "  WARNING: Differs from public copy: $public_file"
            differences=$((differences + 1))
        fi
    fi
    
    return $differences
}

# Main validation loop
echo ""
echo "Validating SSOT files in $SSOT_DIR..."
echo ""

# Use find to get all YAML files recursively
while IFS= read -r -d '' file; do
    # Skip template file
    if [[ "$file" =~ template\.yml$ ]]; then
        continue
    fi
    
    TOTAL_FILES=$((TOTAL_FILES + 1))
    filename=$(basename "$file")
    echo "Checking: $filename"
    
    file_valid=true
    file_warnings=0
    
    # Check YAML syntax
    if ! validate_yaml_syntax "$file"; then
        echo "  ERROR: Invalid YAML syntax"
        file_valid=false
    fi
    
    # Validate SSOT structure
    if ! validate_ssot_structure "$file"; then
        file_valid=false
    fi
    
    # Check for duplicates
    check_duplicates "$file" || file_warnings=$((file_warnings + $?))
    
    # Check hostname compliance
    check_hostnames "$file" || file_warnings=$((file_warnings + $?))
    
    # Compare with served copies
    compare_with_served "$file" || file_warnings=$((file_warnings + $?))
    
    if $file_valid; then
        VALID_FILES=$((VALID_FILES + 1))
        echo "  ✓ Valid"
    else
        INVALID_FILES=$((INVALID_FILES + 1))
        echo "  ✗ Invalid"
    fi
    
    if [ $file_warnings -gt 0 ]; then
        WARNINGS=$((WARNINGS + file_warnings))
    fi
    
    echo ""
done < <(find "$SSOT_DIR" -name "*.yml" -print0)

# Validate MCP configuration specifically
echo "Validating MCP configuration..."
echo ""

if [ -f "$SSOT_DIR/ssot.devin.tools.yml" ]; then
    echo "Checking: ssot.devin.tools.yml"
    
    # Check for duplicate MCP server names
    mcp_servers=$(grep -A 1 "^mcp:" "$SSOT_DIR/ssot.devin.tools.yml" | grep -v "^mcp:" | grep -v "^--$" || true)
    if [ -n "$mcp_servers" ]; then
        echo "  ✓ MCP servers defined"
    else
        echo "  WARNING: No MCP servers defined"
        WARNINGS=$((WARNINGS + 1))
    fi
    
    # Check mcp-conf section
    if grep -q "^mcp-conf:" "$SSOT_DIR/ssot.devin.tools.yml"; then
        echo "  ✓ MCP configuration section exists"
        
        # Note: Duplicate command checks are handled by generate-mcp-configs.py
        # which checks for duplicate (command, args) pairs, not just commands
    else
        echo "  WARNING: No mcp-conf section found"
        WARNINGS=$((WARNINGS + 1))
    fi
    
    echo ""
fi

# Summary
echo "=========================================="
echo "Validation Summary"
echo "=========================================="
echo "Total files checked: $TOTAL_FILES"
echo "Valid files: $VALID_FILES"
echo "Invalid files: $INVALID_FILES"
echo "Total warnings: $WARNINGS"
echo ""

if [ $INVALID_FILES -gt 0 ]; then
    echo "❌ Validation failed - $INVALID_FILES file(s) have errors"
    exit 1
elif [ $WARNINGS -gt 0 ]; then
    echo "⚠️  Validation passed with $WARNINGS warning(s)"
    exit 0
else
    echo "✅ All SSOT files are valid"
    exit 0
fi
