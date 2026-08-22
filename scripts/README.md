# Chaba-Yomi Scripts

Utility scripts for chaba-yomi project operations and maintenance.

## Available Scripts

### migrate-yomi-to-mddb.py

Migrate Yomi LINE conversations to MDDB (Multi-Document Database) for enhanced search capabilities.

**Purpose**: Convert Yomi JSON conversation data to MDDB collections with Thai language support and semantic search.

**Usage**:
```bash
# Basic migration (uses default paths)
python scripts/migrate-yomi-to-mddb.py

# Custom source and server
python scripts/migrate-yomi-to-mddb.py --source /path/to/yomi --server http://localhost:9001

# Dry run to validate data without migrating
python scripts/migrate-yomi-to-mddb.py --dry-run
```

**Requirements**:
- Python 3.6+
- requests library
- MDDB server running (default: http://localhost:9001)
- Yomi data directory with conversations.json and messages/ subdirectory

**Output**:
- Conversations organized by category into MDDB collections
- Thai language support with proper encoding
- Rich metadata for search and filtering
- Detailed logging to `migrate-yomi.log`

**Collections Created**:
- `yomi-general` - Uncategorized conversations
- `yomi-personal` - Personal conversations
- `yomi-official` - Official/business accounts
- `yomi-groups` - Group chats
- `yomi-work` - Work-related conversations

**Documentation**: See `docs/kb/yomi-mddb-migration.md` for detailed migration guide.

## Script Development Guidelines

When adding new scripts:

1. **Add proper documentation**: Include docstrings, usage examples, and help text
2. **Use logging**: Implement proper logging for debugging and monitoring
3. **Error handling**: Add comprehensive error handling and user-friendly messages
4. **Configuration**: Support command-line arguments for flexibility
5. **Testing**: Include dry-run modes where appropriate
6. **Documentation**: Update this README and related KB entries

## Common Patterns

### Argument Parsing
```python
import argparse

parser = argparse.ArgumentParser(description='Script description')
parser.add_argument('--source', default='default_path', help='Source directory')
parser.add_argument('--dry-run', action='store_true', help='Validate without changes')
args = parser.parse_args()
```

### Logging Setup
```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('script.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
```

### Error Handling
```python
try:
    # Main operation
    result = perform_operation()
    logger.info("Operation completed successfully")
    return 0
except FileNotFoundError as e:
    logger.error(f"File not found: {e}")
    return 1
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    return 1
```

## Maintenance

- Test scripts after any dependency updates
- Update documentation when scripts are modified
- Review logs regularly for script performance issues
- Keep scripts compatible with project Python version

## Related Documentation

- Yomi Migration Guide: `docs/kb/yomi-mddb-migration.md`
- MDDB Collections: `docs/kb/mddb-collections.md`
- MCP Tools: `docs/kb/mcp-tools.md`