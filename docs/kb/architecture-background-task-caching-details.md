---
category: operations
---

# Key Details

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

