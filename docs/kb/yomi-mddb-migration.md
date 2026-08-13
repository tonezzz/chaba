# Yomi to MDDB Migration

Migrated old Yomi files (conversations.json + messages/) to MDDB for archival after Postgres migration, providing enhanced search capabilities and better data organization.

## Context

Old Yomi files were stored as JSON files in `/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi-archive/`. After Postgres migration, these files became redundant but contained valuable historical conversation data. MDDB provides better archival capabilities with search, web UI, and MCP integration compared to file-based storage.

## Migration Details

**Source**: `/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi-archive/`
- `conversations.json` (48K) - Conversation metadata (60 conversations)
- `messages/` directory (2.2M, 64 JSON files) - Individual message arrays

**Target**: MDDB server via MCP API (http://localhost:9001)
- Single `yomi-archive` collection for all archival data
- BM25 search with Thai text support
- Rich metadata for search and filtering
- Web UI access via MDDB Panel

**Migration Script**: `/home/tony/CascadeProjects/chaba-yomi/scripts/migrate-yomi-to-mddb.py`

## Collection Structure

Created single archival collection:

| Collection | Purpose | Document Count |
| --- | --- | --- |
| `yomi-archive` | Old Yomi files archival | 65 documents |

**Breakdown**: 1 conversations metadata document + 64 individual message files

**Total MDDB Database**: 370 documents across 24 collections (84.6 MB)

## Technical Implementation

### MCP API Connection

MDDB uses MCP (Model Context Protocol) for API access. Key discovery:
- Simple HTTP GET requests return 404 errors
- MCP requires specific JSON-RPC POST format: `POST /tools/call` with JSON payload
- Proper format: `{"name": "tool_name", "arguments": {...}}`

### Migration Script Features

1. **Single collection approach**: All archival data in `yomi-archive` collection
2. **English language setting**: Sets `lang: "en"` for proper encoding
3. **Message formatting**: Converts JSON to readable markdown with timestamps
4. **Metadata extraction**: Preserves conversation ID, source, type, archived date
5. **Connection testing**: Verifies MDDB connectivity before migration

### Data Format

**Conversations metadata document**:
```markdown
# Yomi Conversations Archive

**Generated At**: 2026-07-28T01:45:15.364Z
**Total Conversations**: 60

## Conversation List

### Conversation Name (id)
- **Category**: Personal
- **Unread**: 225
- **Last Message**: 1785196148918
- **Summary**: Conversation summary
- **Is Group**: False
```

**Individual message files**:
```markdown
# Messages: conversation_id

**Generated At**: 2026-07-28T01:43:21.303Z
**Total Messages**: 36

## Message History

### timestamp - Sender Name
**From**: user_id
**Text**: message content
**Media**: media_type (if available)
**E2EE**: decrypted_status
**Verified**: integrity_status
```

## Verification

### Search Functionality

**BM25 search**: Works via `search_documents` tool with Thai text support
```bash
curl -X POST http://localhost:9001/tools/call \
  -H "Content-Type: application/json" \
  -d '{"name":"search_documents","arguments":{"collection":"yomi-archive","text":"ประกาษ","limit":3}}'
```

**Thai language support**: Successfully tested with Thai queries (ประกาษ = announcement)
**Response time**: Fast BM25 search with context excerpts

### MDDB Stats

Pre-migration: 305 documents across 23 collections
Post-migration: 370 documents across 24 collections (65 new Yomi archival documents)
Database size: 84.6 MB

## Archive Location

**Original files location** (now removed):
`/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi-archive/`
- `conversations.json` (48K) - removed 2026-08-12
- `messages/` directory (2.2M, 64 files) - removed 2026-08-12

**Primary archive**: MDDB `yomi-archive` collection (65 documents)

## Usage Examples

### Access via MCP API

```bash
# Get MDDB stats
curl -X POST http://localhost:9001/tools/call \
  -H "Content-Type: application/json" \
  -d '{"name":"get_stats","arguments":{}}'

# Search Yomi archive
curl -X POST http://localhost:9001/tools/call \
  -H "Content-Type: application/json" \
  -d '{"name":"search_documents","arguments":{"collection":"yomi-archive","text":"conversations","limit":5}}'

# Thai text search
curl -X POST http://localhost:9001/tools/call \
  -H "Content-Type: application/json" \
  -d '{"name":"search_documents","arguments":{"collection":"yomi-archive","text":"ประกาษ","limit":3}}'
```

### Web Panel Access

MDDB web panel available at http://tony-omen.local:3002/ for manual browsing and search of the yomi-archive collection.

### Migration Script Usage

```bash
# Run migration script
python3 /home/tony/CascadeProjects/chaba-yomi/scripts/migrate-yomi-to-mddb.py

# Script features:
# - Tests MDDB connectivity before migration
# - Migrates conversations.json as metadata document
# - Migrates individual message files as separate documents
# - Provides progress feedback and error handling
```

## Troubleshooting

### MCP Connection Issues

**Symptom**: 404 errors on HTTP GET requests
**Solution**: Use proper MCP JSON-RPC POST format to `/tools/call` endpoint

**Example**:
```bash
# Wrong
curl http://localhost:9001

# Correct
curl -X POST http://localhost:9001/tools/call \
  -H "Content-Type: application/json" \
  -d '{"name":"get_stats","arguments":{}}'
```

### File Location Issues

**Symptom**: conversations.json or messages/ not found
**Solution**: Verify correct source path - files were in `yomi-archive/` not `yomi/`

**Correct path**: `/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi-archive/`

### MDDB Collection Issues

**Symptom**: Unknown tool errors
**Solution**: Use correct MDDB tool names:
- `add_document` for adding documents
- `search_documents` for BM25 search
- `get_stats` for database statistics

## Related Documentation

- MDDB implementation: `/home/tony/CascadeProjects/chaba-kbman/docs/kb/mddb-implementation-complete.md`
- MDDB migration strategy: `/home/tony/CascadeProjects/chaba-kbman/docs/kb/mddb-migration-strategy.md`
- Yomi system documentation: `docs/kb/yomi.md`
- SSOT updates: `docs/overview/ssot.kb.yml` (2026-08-12 session memory)
- Workspace rules: `.windsurfrules` (Yomi Data Archival section)

## Migration Date

2026-08-12 (archive migration and cleanup)

## Documentation Updates

- Updated `docs/overview/ssot.kb.yml` with 2026-08-12 session memory
- Updated `.windsurfrules` with Yomi Data Archival section
- Updated this KB entry to reflect archival approach (vs previous categorization approach)

## Reusability

This archival pattern can be adapted for other JSON-based datasets to MDDB collections. Key components:
- MCP API connection pattern
- Single collection archival approach
- Markdown formatting for searchability
- Metadata extraction for filtering
- Migration script template for future use