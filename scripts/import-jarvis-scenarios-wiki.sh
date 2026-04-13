#!/bin/bash
# Import Jarvis Live Scenarios to MCP Wiki
# Run when wiki server is online

cd /home/chaba/chaba

TITLE="Jarvis Live API Scenarios"
CONTENT=$(cat docs/JARVIS_LIVE_SCENARIOS_WIKI.md)

# Use the wiki MCP import script if available
if [ -f "scripts/import-wiki-api.py" ]; then
    echo "Importing to wiki: $TITLE"
    # The import-wiki-api.py script would need to be adapted
    # For now, manual import via mcp-wiki-client.sh
fi

echo "To manually import:"
echo "1. Start the wiki MCP server"
echo "2. Use mcp-wiki-client.sh with action 'create'"
echo ""
echo "Title: $TITLE"
echo "File: docs/JARVIS_LIVE_SCENARIOS_WIKI.md"
