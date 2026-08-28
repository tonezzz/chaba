---
category: operations
---

# Implementation

### MCP Tool Integration (13 tools)

**Workflow Automation:**
- `kb_workflow_start()` - Complete workflow check before work
- `kb_workflow_end(summary)` - Commit changes and update changelog
- `kb_workflow_check()` - Complete workflow status check

**Git Operations:**
- `kb_git_status()` - Check git status of KB
- `kb_git_diff(file_path)` - Get git diff for KB
- `kb_git_commit(message, files)` - Commit KB changes to git

**Validation & Detection:**
- `kb_check_duplicates()` - Check for duplicate files
- `kb_validate_frontmatter(file_path)` - Validate KB frontmatter
- `kb_generate_frontmatter(title, tags, status)` - Generate frontmatter

**Session Management:**
- `kb_read_current_context()` - Read current context from KB
- `kb_update_current_context(content)` - Update current context in KB
- `kb_read_active_projects()` - Read active projects from KB
- `kb_update_active_projects(content)` - Update active projects in KB
- `kb_add_changelog_entry(entry)` - Add entry to KB changelog
- `kb_session_state()` - Get current KB session state

**Entry Creation:**
- `kb_create_entry(title, content, tags, status)` - Create properly formatted KB entry

### Testing Results

**Comprehensive Test Suite:**
- **Git Operations**: ✅ 3/3 tests passed
- **Duplicate Detection**: ✅ 1/1 test passed
- **KB Validation**: ✅ 2/2 tests passed
- **Session Management**: ✅ 2/2 tests passed
- **Workflow Coordinator**: ✅ 1/1 test passed
- **KB Entry Creation**: ✅ 1/1 test passed
- **Overall**: 10/10 tests passed (100% success rate)

**Comparison with kb-start.sh/kb-end.sh:**
- kb-start.sh: ✅ PASS (KB is in sync)
- mcp-kbman: ✅ PASS (Ready for work)
- Both systems agree on KB state

### Performance Considerations

**Git Operations on GDrive Mount:**
- **Status**: Git operations work but are slower than local filesystem
- **Timeout**: Increased to 120s for git add/commit operations
- **Issues**: Index lock cleanup may be required for failed operations
- **Recommendation**: Use mcp-kbman for light operations, direct git for heavy operations

**Validation Performance:**
- **Status**: Fast with 28 files
- **Optimization**: Skipping templates and historical files improves performance
- **Recommendation**: Current lenient validation approach is appropriate

## Usage/Commands

### Complete Workflow Cycle
```python
# 1. Start check
mcp_call_tool("mcp-kbman", "kb_workflow_start", {})

# 2. Create KB entry
mcp_call_tool("mcp-kbman", "kb_create_entry", {
    "title": "Test Entry",
    "content": "# Test content",
    "tags": ["test"],
    "status": "active"
})

# 3. Commit changes
mcp_call_tool("mcp-kbman", "kb_git_commit", {
    "message": "test: KB workflow test"
})

# 4. End workflow
mcp_call_tool("mcp-kbman", "kb_workflow_end", {
    "summary": "tested KB workflow integration"
})
```

### Individual Operations
```python
# Check git status
mcp_call_tool("mcp-kbman", "kb_git_status", {})

# Check for duplicates
mcp_call_tool("mcp-kbman", "kb_check_duplicates", {})

# Validate frontmatter
mcp_call_tool("mcp-kbman", "kb_validate_frontmatter", {
    "file_path": "hardware/tony-omen/2026-08-11-test.md"
})

# Update current context
mcp_call_tool("mcp-kbman", "kb_update_current_context", {
    "content": "# Updated context"
})
```

## Troubleshooting

### Git Lock Errors
**Issue**: `Unable to create .git/index.lock: File exists`
**Solution**:
- Remove lock file: `rm -f .git/index.lock`
- Check for other git processes running
- Retry git operation after cleanup

### Git Operation Timeout
**Issue**: Git operations timing out on GDrive mount
**Solution**:
- Increased timeout to 120s in configuration
- Consider using direct git for heavy operations
- Check GDrive mount availability and performance

### Validation Errors
**Issue**: Frontmatter validation failing on existing files
**Solution**:
- Use lenient validation (require_frontmatter=False)
- Skip templates and historical entries
- Update validation rules if needed

### Duplicate Detection
**Issue**: False positives in duplicate detection
**Solution**:
- Review duplicate pattern matching
- Check for legitimate uses of numbered files
- Resolve duplicates manually if needed

### Session State Issues
**Issue**: Session files not found or inaccessible
**Solution**:
- Check file paths in configuration
- Verify file permissions
- Ensure KB directory is accessible

## Migration Strategy

### Phase 1: Adoption (Recommended)
1. Use `kb_workflow_start()` before starting work
2. Use mcp-kbman tools for KB operations
3. Use `kb_workflow_end(summary)` when finishing work
4. Keep direct access as fallback for heavy git operations

### Phase 2: Optimization (Future)
1. Add cache files to .gitignore
2. Implement git lock cleanup automation
3. Add performance monitoring for git operations
4. Consider local staging for heavy git operations

### Phase 3: Full Migration (Future)
1. After successful Phase 1, consider full migration
2. Deprecate direct kb-start.sh/kb-end.sh usage
3. Use mcp-kbman as primary KB interface
4. Maintain direct access as emergency fallback

