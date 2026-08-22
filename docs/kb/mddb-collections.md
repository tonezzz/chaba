# MDDB Collection Structure

Documented collection structure in MDDB (Multi-Document Database) as of 2026-08-13.

## Overview

MDDB organizes documents into collections for logical grouping and efficient search. Current system has 24 collections with 370 total documents.

## Collection Categories

### Chaba Collections

Project-specific collections for Chaba lab documentation and assessments.

| Collection | Documents | Purpose |
| --- | --- | --- |
| `chaba-architecture` | 3 | System architecture documentation |
| `chaba-assessments` | 11 | Project assessments and evaluations |
| `chaba-general` | 36 | General Chaba project documentation |
| `chaba-implementation` | 3 | Implementation details and guides |
| `chaba-reports` | 2 | Project reports and summaries |

### Knowledge Base Collections

General knowledge base entries organized by topic.

| Collection | Documents | Purpose |
| --- | --- | --- |
| `kb-development` | 15 | Development practices, testing, automation |
| `kb-features` | 42 | Feature documentation and specifications |
| `kb-operations` | 4 | Operations, monitoring, maintenance |
| `kb-system` | 28 | System infrastructure, security, configuration |

### SSOT Collections

Single Source of Truth documentation for infrastructure and applications.

| Collection | Documents | Purpose |
| --- | --- | --- |
| `ssot-apps` | 15 | Application configurations and metadata |
| `ssot-general` | 15 | General SSOT documentation |
| `ssot-infrastructure` | 10 | Infrastructure and network documentation |

### Trade Project Collections

Knowledge base for trade project specific documentation.

| Collection | Documents | Purpose |
| --- | --- | --- |
| `trade-kb-development` | 20 | Trade project development documentation |
| `trade-kb-features` | 26 | Trade project feature documentation |
| `trade-kb-system` | 13 | Trade project system documentation |

### Yomi Collections

Old Yomi LINE conversation data and new archival data.

| Collection | Documents | Purpose |
| --- | --- | --- |
| `yomi-archive` | 65 | Old Yomi files archival (conversations.json + messages/) |
| `yomi-general` | 20 | Uncategorized LINE conversations |
| `yomi-personal` | 16 | Personal LINE conversations |
| `yomi-official` | 10 | Official/business LINE accounts |
| `yomi-groups` | 8 | LINE group chats |
| `yomi-work` | 6 | Work-related LINE conversations |

**Note**: `yomi-archive` contains migrated old Yomi files (65 documents) as of 2026-08-12. Other yomi collections contain categorized LINE conversation data from earlier migration.

### Memory Collections

System memory and session tracking.

| Collection | Documents | Purpose |
| --- | --- | --- |
| `memory_messages` | 1 | Message memory tracking |
| `memory_sessions` | 1 | Session memory tracking |

## Collection Naming Convention

**Pattern**: `{category}-{subcategory}`

**Categories**:
- `chaba` - Chaba project specific
- `kb` - General knowledge base
- `ssot` - Single Source of Truth
- `trade-kb` - Trade project knowledge base
- `yomi` - Yomi LINE conversations
- `memory` - System memory tracking

**Subcategories**:
- `architecture`, `assessments`, `general`, `implementation`, `reports`
- `development`, `features`, `operations`, `system`
- `apps`, `general`, `infrastructure`
- `general`, `personal`, `official`, `groups`, `work`
- `messages`, `sessions`

## Metadata Standards

### Common Metadata Fields

Most documents include these metadata fields:
- `title` - Document title
- `source` - Data source (e.g., "yomi-line", "chaba-kbman")
- `category` - Document category
- `migrated_at` - Migration timestamp (for migrated data)

### Yomi-Specific Metadata

Yomi collections include additional fields:
- `is_group` - Boolean for group chats
- `unread_count` - Number of unread messages
- `message_count` - Total messages in conversation
- `last_message_time` - Timestamp of last message
- `migrated_at` - Migration timestamp

## Search Strategy

### Collection Selection

Choose target collection based on search intent:
- **Chaba documentation**: Use `chaba-*` collections
- **General knowledge**: Use `kb-*` collections
- **Infrastructure info**: Use `ssot-infrastructure`
- **LINE conversations**: Use `yomi-*` collections
- **Trade project**: Use `trade-kb-*` collections

### Search Methods

**BM25 Search** (exact keyword matching):
```python
mcp_call_tool("mddb", "search_documents", {
  "collection": "kb-system",
  "filter_meta": {"category": "security"},
  "limit": 10
})
```

**Semantic Search** (meaning-based):
```python
mcp_call_tool("mddb", "semantic_search", {
  "query": "docker container configuration",
  "collection": "kb-system",
  "limit": 5
})
```

**Metadata Filtering**:
```python
mcp_call_tool("mddb", "search_documents", {
  "collection": "yomi-personal",
  "filter_meta": {"unread_count": [">", "10"]},
  "limit": 5
})
```

## Collection Statistics

**Total Documents**: 370
**Total Revisions**: 532
**Total Meta Indices**: 1,702
**Database Size**: 84.6 MB
**Database Path**: `/app/data/mddb.db`

**Largest Collections**:
1. `kb-features`: 42 documents
2. `chaba-general`: 36 documents
3. `kb-system`: 28 documents
4. `yomi-archive`: 65 documents (new archival collection)
5. `trade-kb-features`: 26 documents

## Maintenance

### Adding New Collections

When creating new collections:
1. Follow naming convention: `{category}-{subcategory}`
2. Update this documentation
3. Consider metadata standards for consistency
4. Test search functionality

### Collection Cleanup

- Archive unused collections rather than deleting
- Update documentation when collections are renamed
- Consider data migration when restructuring

## Related Documentation

- Yomi to MDDB Migration (`docs/kb/yomi-mddb-migration.md`)
- MCP Tools Inventory (`docs/kb/mcp-tools.md`)
- MDDB server documentation

## Last Updated

2026-08-13 (updated for yomi-archive collection addition)