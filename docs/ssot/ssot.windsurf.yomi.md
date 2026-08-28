## Yomi Data Archival

- **Primary Archive**: MDDB knowledge base (yomi-archive collection)
- **Access Methods**:
  - MDDB Panel: http://tony-omen.local:3002/
  - MCP API: http://localhost:9001/tools/call
  - Migration script: scripts/migrate-yomi-to-mddb.py
- **Archive Content**: Old Yomi files (conversations.json, messages/) migrated to MDDB
- **Search Capabilities**: BM25 search with Thai text support, semantic search via Ollama
- **Original Files**: Removed from chaba/stacks/web/public/apps/yomi-archive/ after successful migration
- **Migration Date**: 2026-08-12 (65 documents: conversations + 64 message files)
- **Benefits**: Structured storage, search capabilities, web UI, MCP integration, automated backup

## Auto KB review at end of each session (MANDATORY)

At the end of every assistant response that answers or completes a user request — including small test questions — you MUST append a markdown section titled exactly `KB review`. In that section, briefly list any KB-worthy facts from the conversation: decisions, discoveries, infrastructure changes, conventions, and workarounds. Before saving anything, check existing memories and update or archive stale entries rather than duplicating. Create new memories in the correct corpus with clear titles and tags. Do NOT save temporary commands, one-off output, or obvious trivia.

## Automatic KB Creation Policy (MANDATORY)

**KB-Worthy Triggers**: Automatically suggest KB entry creation when:
- Fixing significant bugs or issues (especially data corruption, security vulnerabilities)
- Discovering new patterns, workarounds, or best practices
- Implementing new systems, integrations, or technologies
- Finding configuration optimizations or performance improvements
- Identifying language-specific challenges (Thai/English mixed content, encoding issues)
- Documenting root cause analyses of complex problems
- Creating reusable patterns or conventions

**KB Suggestion Process**:
1. When encountering KB-worthy information, immediately suggest creating a KB entry
2. Provide suggested KB entry title and brief description
3. Explain why it's KB-worthy (operational value, reusability, prevention)
4. Ask user for confirmation before creating the entry
5. Follow KB entry format with comprehensive details

**Redundancy Check**:
- Before suggesting new KB entry, check existing KB entries for overlap
- Update existing entries instead of creating duplicates
- Archive outdated entries rather than deleting
- Maintain single source of truth for each topic
