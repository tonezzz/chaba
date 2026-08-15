#!/bin/bash
set -e

echo "🔄 Migrating KB content to MDDB using MCP API..."

# Variables
KB_DIR="/home/tony/CascadeProjects/chaba-kbman/docs/kb"
MDBB_SERVER="http://localhost:9001"

# Count files
TOTAL_FILES=$(find "$KB_DIR" -name "*.md" | wc -l)
echo "📁 Found $TOTAL_FILES markdown files to migrate"

# Migrate all files
COUNT=0
for file in "$KB_DIR"/*.md; do
    
    filename=$(basename "$file" .md)
    
    # Determine collection based on filename pattern
    if [[ "$filename" =~ (system|infrastructure|architecture|security) ]]; then
        collection="kb-system"
    elif [[ "$filename" =~ (development|testing|automation|javascript) ]]; then
        collection="kb-development"
    elif [[ "$filename" =~ (operations|monitoring|maintenance|backup) ]]; then
        collection="kb-operations"
    else
        collection="kb-features"
    fi
    
    echo "📄 Migrating: $filename -> $collection"
    
    # Read content and escape for JSON
    content=$(cat "$file" | sed 's/\\/\\\\/g' | sed 's/"/\\"/g' | sed ':a;N;$!ba;s/\n/\\n/g')
    
    # Add document via MCP API
    curl -s -X POST "$MDBB_SERVER/tools/call" \
      -H "Content-Type: application/json" \
      -d "{\"name\":\"add_document\",\"arguments\":{\"collection\":\"$collection\",\"key\":\"$filename\",\"lang\":\"en\",\"content_md\":\"$content\",\"meta\":{\"title\":\"$filename\",\"source\":\"chaba-kbman\",\"category\":\"migrated\"}}}" > /dev/null
    
    echo "✅ Migrated: $filename"
    ((COUNT++))
done

echo "🎉 KB migration completed!"
echo "📊 Files migrated: $COUNT"