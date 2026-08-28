---
category: operations
---

# Implementation

### Default Task Setup
```python
def setup_default_tasks(scheduler: TaskScheduler):
    """Configure default background tasks."""
    
    # File index generation (every 60s)
    scheduler.register_task(
        task_id="file_index_generator",
        interval_seconds=60,
        function=generate_file_index_task
    )
    
    # Search index generation (every 300s)
    scheduler.register_task(
        task_id="search_index_generator", 
        interval_seconds=300,
        function=generate_search_index_task
    )
    
    # Cache cleanup (every 3600s)
    scheduler.register_task(
        task_id="cache_cleanup",
        interval_seconds=3600,
        function=cache_cleanup_task
    )
```

### Cache Storage Structure
```
/home/tony/.cache/mcp-kbman/pre_generated/
├── file_index_index.json           # File listing cache
├── search_index_index.json         # Search index cache
├── document_summaries_index.json   # Document summaries cache
└── metadata.json                   # Cache metadata
```

### Performance Measurements

#### File Index Generation
- **Uncached**: ~0.042s (direct filesystem scan)
- **Cached**: ~0.004s (JSON cache read)
- **Improvement**: 90% faster

#### Search Index Generation
- **Uncached**: ~0.15s (Whoosh indexing)
- **Cached**: ~0.004s (JSON cache read)
- **Improvement**: 97% faster

#### Search Query Performance
- **Uncached**: ~0.1-0.3s (Whoosh search)
- **Cached**: ~0.004s (result cache)
- **Improvement**: 98% faster

## Usage/Commands

### MCP Tool Integration
```python
# Get scheduler status
mcp_call_tool("mcp-kbman", "get_scheduler_status", {})

# Trigger specific task manually
mcp_call_tool("mcp-kbman", "trigger_task", {"task_id": "file_index_generator"})

# Get task results
mcp_call_tool("mcp-kbman", "get_task_results", {"task_id": "file_index_generator"})

# Get pre-generated cache statistics
mcp_call_tool("mcp-kbman", "get_pre_generated_stats", {})

# Clear specific cache
mcp_call_tool("mcp-kbman", "clear_pre_generated_cache", {"data_type": "file_index"})
```

### Direct Python Usage
```python
from tasks.pre_generator import DocumentPreGenerator
from tasks.scheduler import TaskScheduler

# Generate file index
generator = DocumentPreGenerator()
file_index = generator.generate_file_index()

# Setup scheduler
scheduler = TaskScheduler()
setup_default_tasks(scheduler)
scheduler.start()

# Trigger task manually
scheduler.trigger_task("file_index_generator")
```

## Troubleshooting

### Tasks Not Running
**Issue**: Background tasks not executing
**Solution**:
- Check scheduler status: `get_scheduler_status()`
- Verify scheduler is enabled: `SCHEDULER_ENABLED=True`
- Check task intervals are configured correctly
- Review task error counts in status

### Cache Not Updating
**Issue**: Cached data not refreshing
**Solution**:
- Check task execution frequency
- Verify TTL settings are appropriate
- Manually trigger task: `trigger_task(task_id)`
- Check cache expiration times

### High Memory Usage
**Issue**: Cache consuming too much memory
**Solution**:
- Reduce cache size limit: `MAX_CACHE_SIZE_MB`
- Increase cache cleanup frequency
- Reduce TTL for pre-generated data
- Monitor cache statistics regularly

### Cache Corruption
**Issue**: Cache files corrupted or invalid
**Solution**:
- Clear specific cache: `clear_pre_generated_cache(data_type)`
- Clear all caches: `clear_pre_generated_cache()`
- Regenerate caches by triggering tasks
- Check cache file permissions

### Performance Degradation
**Issue**: System performance degraded with background tasks
**Solution**:
- Increase task intervals (reduce frequency)
- Disable unnecessary tasks
- Monitor CPU/memory usage during task execution
- Consider offloading to separate process

