# Yomi Architecture: Separated Fetch and Process

## Overview

Yomi's conversation update pipeline has been separated into two distinct phases:
1. **Fetch Phase**: Pull raw data from LINE API
2. **Process Phase**: Summarize, categorize, and store in database

## Architecture

### Phase 1: Fetch (`fetch-conversations.mjs`)

**Purpose**: Fetch raw conversation data from LINE API

**Operations**:
- Connect to Yomi MCP server
- List conversations (up to 200)
- Fetch messages for each conversation
- Store raw data in `fetch-data/` directory
- Batch processing (10 conversations at a time)
- 2-second delay between batches to avoid rate limiting

**Output**:
- `fetch-data/{chatId}.json` - Raw message data per conversation
- `fetch-data/fetch-metadata.json` - Fetch operation metadata

**API Endpoint**: `POST /api/yomi/fetch?chat={id}` (optional chat parameter)

**Advantages**:
- Fast - only fetches data, no processing
- Can be run independently
- Data can be inspected before processing
- Retry on fetch failures without re-processing

### Phase 2: Process (`process-conversations.mjs`)

**Purpose**: Process fetched data and update database

**Operations**:
- Read raw data from `fetch-data/` directory
- Generate summaries using Llama
- Evaluate summary quality
- Categorize conversations
- Update PostgreSQL database
- Manage summary cache

**Input**: Data from `fetch-data/` directory

**Output**: Updated PostgreSQL database

**API Endpoint**: `POST /api/yomi/process?chat={id}&force=true` (optional parameters)

**Advantages**:
- Can be run multiple times on same data
- Force re-summarization with `--force` flag
- Quality-aware processing
- Independent of LINE API availability

### Legacy: Combined (`update-conversations.mjs`)

**Purpose**: Original combined operation (still available)

**Operations**: Fetch + Process in one operation

**Use Case**: Quick single-conversation updates

**API Endpoint**: `POST /api/yomi/refresh?chat={id}`

## API Endpoints

### Fetch Operations
```
POST /api/yomi/fetch                    # Fetch all conversations
POST /api/yomi/fetch?chat={id}          # Fetch single conversation
GET  /api/yomi/fetch?chat={id}          # Fetch single conversation
```

### Process Operations
```
POST /api/yomi/process                  # Process all conversations
POST /api/yomi/process?chat={id}        # Process single conversation
POST /api/yomi/process?force=true       # Force re-summarization
GET  /api/yomi/process?chat={id}        # Process single conversation
```

### Legacy Operations
```
POST /api/yomi/refresh                  # Combined fetch + process (all)
POST /api/yomi/refresh?chat={id}        # Combined fetch + process (single)
POST /api/yomi/refresh?force=true       # Force refresh (bypass cache)
```

## Workflow Examples

### Single Conversation Update (New)
```bash
# Step 1: Fetch
curl -X POST http://localhost:3000/api/yomi/fetch?chat=xxx

# Step 2: Process
curl -X POST http://localhost:3000/api/yomi/process?chat=xxx
```

### Batch Update (New)
```bash
# Step 1: Fetch all
curl -X POST http://localhost:3000/api/yomi/fetch

# Step 2: Process all
curl -X POST http://localhost:3000/api/yomi/process
```

### Force Re-summarization
```bash
# Re-process with force flag
curl -X POST http://localhost:3000/api/yomi/process?force=true
```

### Legacy (Still Works)
```bash
# Combined operation
curl -X POST http://localhost:3000/api/yomi/refresh?chat=xxx
```

## UI Changes

### Chat Page (chat.html)
- **Refresh button**: Now performs 2-step operation (fetch → process)
- **Force button**: Bypasses cache during processing
- **Status updates**: Shows "Fetching..." → "Processing..." → "Updated"

### Main Page (index.html)
- **Refresh All button**: Now performs 2-step operation (fetch → process)
- **Status updates**: Shows progress through both phases

## Benefits

### Performance
- **Faster feedback**: Fetch completes quickly, processing can run in background
- **Parallel processing**: Can fetch and process different conversations simultaneously
- **Selective re-processing**: Re-process without re-fetching

### Reliability
- **Retry capability**: Can retry failed fetches without re-processing
- **Data inspection**: Can inspect raw data before processing
- **Incremental updates**: Can process only changed conversations

### Flexibility
- **Independent phases**: Run fetch and process at different times
- **Debugging**: Can debug processing without re-fetching
- **Testing**: Can test processing with mock data

## Recommendations

### Automation
Create systemd timers for each phase:
```bash
# Fetch every 15 minutes
[Unit]
Description=Yomi Fetch
[Service]
ExecStart=/usr/bin/node /home/tony/CascadeProjects/chaba/scripts/yomi/fetch-conversations.mjs

[Timer]
OnCalendar=*:0/15

# Process every 30 minutes
[Unit]
Description=Yomi Process
[Service]
ExecStart=/usr/bin/node /home/tony/CascadeProjects/chaba/scripts/yomi/process-conversations.mjs

[Timer]
OnCalendar=*:0/30
```

### Monitoring
Add status endpoints to track each phase:
```
GET /api/yomi/fetch-status      # Last fetch time, success/fail counts
GET /api/yomi/process-status    # Last process time, quality metrics
```

### Queue System
Consider adding a queue for:
- Prioritizing important conversations
- Throttling processing to avoid overwhelming Llama
- Background processing with status updates

## Migration

### Existing Code
- `update-conversations.mjs` still works (legacy)
- No breaking changes to existing API endpoints
- Gradual migration to new separated endpoints

### Recommended Migration Path
1. Keep using legacy endpoint for single-chat updates
2. Use new separated endpoints for batch operations
3. Add automation with systemd timers
4. Monitor and optimize each phase independently
