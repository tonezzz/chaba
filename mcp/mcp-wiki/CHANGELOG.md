# Changelog

## [1.1.0] - 2026-04-15

### Major Changes

#### 1. PostgreSQL-Only Migration
- **Removed SQLite support entirely** - Simplified codebase by removing dual-database complexity
- Removed `sqlite3` dependency from `package.json`
- Database helpers now use clean PostgreSQL queries without conditional branches
- Default configuration uses PostgreSQL with pgvector support

#### 2. Implemented `wiki_smart_research` Tool
- **Previously registered but not implemented** - Now fully functional
- Smart article lookup using query analysis with semantic caching
- Workflow:
  1. Analyzes query intent and extracts keywords
  2. Tries exact match first
  3. Falls back to hybrid search (keyword + semantic)
  4. Synthesizes results with relevance scoring
  5. Returns formatted research report

### Code Quality Improvements

#### Database Layer Simplification
All database helpers simplified from ~50-70 lines to ~10-20 lines:
- `searchArticles()` - Removed SQLite fallback
- `getArticle()` - Removed SQLite branch
- `createArticle()` - Removed SQLite branch
- `updateArticle()` - Removed SQLite branch
- `deleteArticle()` - Removed SQLite branch
- `updateArticleMetadata()` - Removed SQLite branch
- `createRevision()` - Removed SQLite branch
- `getArticleRevisions()` - Removed SQLite branch
- `getRevision()` - Removed SQLite branch
- `listArticles()` - Removed SQLite branch

#### Configuration Cleanup
- Removed `USE_POSTGRES` environment variable (always true)
- Removed `WIKI_USE_POSTGRES` check
- Removed `WIKI_DB_PATH` and `DATA_DIR` (SQLite artifacts)
- Simplified `initDatabase()` to PostgreSQL-only

### Stack Configuration Updates

#### `stacks/pc1-wiki/`
- Updated `docker-compose.yml` to use PostgreSQL instead of SQLite
- Added local PostgreSQL service with pgvector
- Removed VPN network dependency
- Created `.env.example` for configuration
- Updated `README.md` with PostgreSQL info

### Documentation Updates

#### `MCP_TOOLS_GUIDE.md`
- Added `wiki_smart_research` to tool list
- Added revision control tools: `wiki_get_history`, `wiki_revert`, `wiki_diff`

### Files Changed

**Core:**
- `mcp/mcp-wiki/index.js` - Major refactoring, removed SQLite code
- `mcp/mcp-wiki/package.json` - Removed sqlite3, bumped version
- `mcp/mcp-wiki/Dockerfile` - Updated comments

**Stacks:**
- `stacks/pc1-wiki/docker-compose.yml` - PostgreSQL migration
- `stacks/pc1-wiki/README.md` - Updated documentation
- `stacks/pc1-wiki/.env.example` - New file

**Documentation:**
- `mcp/mcp-wiki/MCP_TOOLS_GUIDE.md` - Added missing tools
- `mcp/mcp-wiki/CHANGELOG.md` - New file (this file)

### Migration Notes

For existing SQLite deployments:
1. Export data from SQLite using `wiki-knowledge.py` or direct SQL dump
2. Set up PostgreSQL (local or via idc1-db stack)
3. Import data into PostgreSQL
4. Update environment variables to use `DATABASE_URL`

No breaking changes for existing PostgreSQL deployments (idc1-db stack).
