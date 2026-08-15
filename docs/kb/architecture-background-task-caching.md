---
title: Background Task Caching System
description: Periodic pre-generation system with configurable intervals achieving 90%+ performance improvement through background caching in mcp-kbman
tags: [mcp-kbman, caching, background-tasks, performance, pre-generation]
created: 2026-08-11
updated: 2026-08-11
category: operations
related: [mcp-kbman-architecture.md, ../../CascadeProjects/chaba/docs/kb/mcp-tools.md, ../../CascadeProjects/chaba/docs/kb/system-automation.md]
search_keywords: [background tasks, pre-generation, caching, performance optimization, periodic tasks]
---

# Background Task Caching System

## What it is

Periodic pre-generation system with configurable intervals achieving 90%+ performance improvement through background caching in mcp-kbman MCP server for knowledge base management.

## Context/Background

Implemented on 2026-08-11 as part of mcp-kbman development to address performance concerns with repeated file listing and search operations. The system pre-generates commonly accessed data (file indexes, search indexes) and caches results with TTL-based expiration to reduce repeated expensive operations.

## Key Details

### Technical Details
- **Task Scheduler**: Thread-based background scheduler
- **Pre-Generation**: File indexes, search indexes, document summaries
- **Cache Strategy**: TTL-based with automatic cleanup
- **Performance**: 90%+ improvement for cached operations
- **Storage**: JSON-based cache files with metadata

### Task Configuration

#### Configurable Intervals
```python
# Background Task Intervals
FILE_INDEX_INTERVAL_SECONDS = 60      # File listing every 60s
SEARCH_INDEX_INTERVAL_SECONDS = 300   # Search indexing every 5min
CACHE_CLEANUP_INTERVAL_SECONDS = 3600  # Cache cleanup every hour
```

#### Cache TTL Settings
```python
# Cache Time-to-Live
SEARCH_CACHE_TTL_HOURS = 24           # Search cache for 24 hours
PRE_GENERATED_TTL_HOURS = 1           # Pre-generated data for 1 hour
CACHE_TTL_HOURS = 24                  # General cache for 24 hours
```

#### Cache Size Limits
```python
# Cache Management
MAX_CACHE_SIZE_MB = 100               # Maximum cache size 100MB
ENABLE_PRE_GENERATION = True          # Enable background pre-generation
ENABLE_SEARCH_CACHING = True          # Enable search result caching
```

### Component Architecture

#### 1. PreGenerator (`tasks/pre_generator.py`)
**Purpose**: Pre-generates commonly accessed data for performance

**Responsibilities**:
- File index generation (directory listings)
- Search index generation (Whoosh indexing)
- Document summary generation
- Cache file management with TTL
- Cache statistics tracking

**Key Methods**:
- `generate_file_index()` - Generate file listing cache
- `generate_search_index()` - Generate search index cache
- `generate_document_summaries()` - Generate document summaries
- `clear_cache(data_type)` - Clear specific cache type
- `get_cache_stats()` - Get cache statistics

**Cache Structure**:
```python
class PreGeneratedData(BaseModel):
    data_type: str           # Type of cached data
    source_path: str         # Source directory path
    data: dict               # Cached data
    size_bytes: int          # Cache file size
    checksum: str            # Data integrity checksum
    generated_at: datetime   # Generation timestamp
    expires_at: datetime     # Expiration timestamp
```

#### 2. TaskScheduler (`tasks/scheduler.py`)
**Purpose**: Manages periodic background task execution

**Responsibilities**:
- Task registration and scheduling
- Thread-based task execution
- Task result tracking
- Scheduler status monitoring
- Task lifecycle management

**Key Methods**:
- `register_task(task_id, interval, function)` - Register periodic task
- `start()` - Start scheduler
- `stop()` - Stop scheduler
- `trigger_task(task_id)` - Manually trigger task
- `get_task_results(task_id)` - Get recent task results
- `get_status()` - Get scheduler status

**Task Definition**:
```python
class TaskDefinition(BaseModel):
    task_id: str             # Unique task identifier
    interval_seconds: int     # Execution interval
    function: Callable        # Task function
    last_run: Optional[datetime] = None
    last_result: Optional[dict] = None
    error_count: int = 0
    enabled: bool = True
```

#### 3. Task Models (`tasks/models.py`)
**Purpose**: Data models for task and cache management

**Responsibilities**:
- Pydantic models for task definitions
- Cache data models with validation
- Result tracking models
- Metadata models

**Key Models**:
- `TaskDefinition` - Task configuration and state
- `PreGeneratedData` - Cache data with metadata
- `TaskResult` - Task execution results
- `CacheStats` - Cache statistics

## Implementation

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

## Performance Optimization

### Tuning Guidelines
- **High-frequency changes**: Reduce intervals (30s file index)
- **Low-frequency changes**: Increase intervals (10min search index)
- **Memory constraints**: Reduce cache size and TTL
- **CPU constraints**: Increase intervals and reduce concurrent tasks

### Monitoring
- **Task execution time**: Track in task results
- **Cache hit rates**: Monitor cache statistics
- **Memory usage**: Monitor cache size
- **Error rates**: Track task error counts

### Best Practices
- **Start conservative**: Longer intervals, smaller caches
- **Monitor performance**: Adjust based on actual usage
- **Cache hot data**: Focus on frequently accessed data
- **Clean up regularly**: Automatic cache cleanup prevents bloat

## Related Documentation

- **[mcp-kbman-architecture.md](meta/mcp-kbman-architecture.md)** - Search architecture details
- **[mcp-tools.md](../../CascadeProjects/chaba/docs/kb/mcp-tools.md)** - MCP server inventory
- **[system-automation.md](system-automation.md)** - Existing automation patterns
- **[kb-workflow-integration.md](meta/kb-workflow-integration.md)** - KB workflow compliance

## Tags

- **mcp-kbman**: MCP knowledge base management server
- **caching**: Cache strategy and implementation
- **background-tasks**: Periodic task execution
- **performance**: Performance optimization
- **pre-generation**: Data pre-generation strategy
- **automation**: Task automation and scheduling