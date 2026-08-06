# Yomi LINE Web App

## What it is

A static web view served from `http://tony-omen.local:8080/apps/yomi/`.
It lists LINE conversations from the Yomi MCP server and lets you click a title to see recent messages. Each conversation also has an `↗` icon that opens a full single-conversation view (`chat.html?chat=<chatId>`) in a new tab.

## Architecture (Post-Improvement)

Yomi has been split into a two-stage pipeline for better reliability and monitoring:

### Stage 1: Fetch (`fetch-conversations.mjs`)
- Connects to Yomi MCP server
- Fetches conversation list (limit: 200)
- Downloads messages for each conversation (100 messages per chat)
- Saves to `fetch-data/<chatId>.json` with metadata
- Updates conversations table in PostgreSQL
- Runs every 15 minutes via systemd timer

### Stage 2: Process (`process-conversations.mjs`)
- Reads from `fetch-data/` directory
- Generates AI summaries using Llama (Phi-3-mini-4k-instruct-q4)
- Categorizes conversations
- Generates daily summaries (events, actions, topics per date)
- Updates summaries and categories in PostgreSQL
- Tracks processing status in `process-status.json`
- Runs every 5 minutes via systemd timer

### API Server (`yomi-api.mjs`)
- HTTP API on port 3000 (default)
- **Systemd Service**: `yomi-api.service` (auto-restart enabled)
- Endpoints:
  - `/api/yomi/health` - Health check
  - `/api/yomi/conversations` - List all conversations
  - `/api/yomi/messages?chat=<id>` - Get messages for a conversation
  - `/api/yomi/daily?chat=<id>` - Get daily summaries
  - `/api/yomi/refresh?chat=<id>` - Manual refresh trigger
  - `/api/yomi/send` - Send a message
  - `/api/yomi/media/<chatId>/<messageId>` - Download media
  - `/api/yomi/last-updated` - Last database update timestamp
  - `/api/yomi/fetch?chat=<id>` - Trigger fetch stage manually
  - `/api/yomi/process?chat=<id>&force=<bool>` - Trigger process stage manually
  - `/api/yomi/activity-status` - Comprehensive system status and processing state
  - `/api/yomi/summarization-status` - Summarization statistics and quality metrics
  - `/api/yomi/summary-quality` - Detailed quality metrics per conversation
  - `/api/yomi/resummarize` - Trigger re-summarization of conversations
  - `/api/yomi/rate-limiter-status` - Rate limiter and circuit breaker status

## Key files

| File | Purpose |
|------|---------|
| `chaba/stacks/web/public/apps/yomi/index.html` | Conversation list, inline message toggle, new-tab icon |
| `chaba/stacks/web/public/apps/yomi/chat.html` | Full single-conversation view |
| `chaba/stacks/web/public/apps/yomi/.gitignore` | Ignores generated `conversations.json` and `messages/` |
| `chaba/scripts/yomi/fetch-conversations.mjs` | Stage 1: Fetch conversations from LINE API |
| `chaba/scripts/yomi/process-conversations.mjs` | Stage 2: Process and summarize conversations |
| `chaba/scripts/yomi/yomi-api.mjs` | HTTP API server for Yomi data |
| `chaba/scripts/yomi/categorize-conversations.mjs` | Conversation categorization logic |
| `chaba/scripts/yomi/summary-utils.mjs` | Summary generation and quality evaluation |
| `chaba/scripts/yomi/db.mjs` | PostgreSQL database connection |
| `chaba/stacks/web/Caddyfile` | `handle_path /apps/yomi/*` serves `/srv/public/apps/yomi` |

## Data directory

Yomi stores the LINE session and search index in `~/.local/share/yomi`.
Both the Claude Desktop and Windsurf MCP configs must run `/home/tony/.yomi/mcpb/run.mjs` **without** overriding `YOMI_DATA_DIR` so they share the same session.
Only one Yomi MCP server can hold `search-index.db` at a time.

## Systemd Timers

Yomi uses systemd timers for automated operation:

### API Server (`yomi-api.service`)
- **Purpose**: HTTP API server for Yomi data
- **Location**: `/etc/systemd/system/yomi-api.service`
- **Enabled**: Yes (auto-restart on failure)
- **Status**: Active (added 2026-08-04)

### Fetch Timer (`yomi-fetch.timer`)
- **Frequency**: Every 15 minutes (`*:0/15`)
- **Service**: `yomi-fetch.service`
- **Location**: `/etc/systemd/system/yomi-fetch.timer`
- **Enabled**: Yes (symlinked in `timers.target.wants`)

### Process Timer (`yomi-process.timer`)
- **Frequency**: Every minute during midnight to 7 AM (`*-*-* 00,01,02,03,04,05,06,07:*:0/1`)
- **Service**: `yomi-process.service`
- **Location**: `/etc/systemd/system/yomi-process.timer`
- **Enabled**: Yes (symlinked in `timers.target.wants`)
- **Time-Restricted Execution**: Configured to run only during overnight hours (00:00-07:00) to avoid GPU resource contention during daytime usage (updated 2026-08-04)

### Management Commands
```bash
# Check timer status
systemctl list-timers yomi-*

# View timer logs
journalctl -u yomi-fetch.timer
journalctl -u yomi-process.timer
journalctl -u yomi-api.service

# Manual trigger
systemctl start yomi-fetch.service
systemctl start yomi-process.service
systemctl restart yomi-api.service
```

## Manual Refreshing

For manual refresh (legacy method):

```bash
node /home/tony/CascadeProjects/chaba/scripts/yomi/update-conversations.mjs
```

This script (now superseded by the two-stage pipeline):

1. Connects to the Yomi MCP server.
2. Calls `list_conversations` with `limit: 200` and writes `conversations.json`.
3. For each conversation calls `get_chat_messages` with `count: 20`, parses the CSV-ish text response, and writes `messages/<chatId>.json`.

## `get_chat_messages` parser

The tool returns rows of 9 fields separated by commas, with the first line as a header. Quoted fields may contain commas, newlines, and `\"` escapes. The script tokenizer:

- Skips leading whitespace outside quotes.
- Reads quoted fields until an unescaped `"`.
- Translates `\n` / `\t` escape sequences.
- Stops unquoted fields at `,` or `\n`.

Parsed objects look like:

```json
{
  "createdTime": 1785026885175,
  "deliveredTime": 1785026885175,
  "from": "u3da49a66bb90d1d8fe5e12b1aaa19325",
  "fromName": "YU DEE.jam",
  "id": "624440565954248722",
  "mediaType": null,
  "mentions": null,
  "text": "message text with newlines",
  "e2eeDecrypted": null
}
```

## Model Configuration

### Current Summarization Model
- **Model**: Phi-3-mini-4k-instruct-q4 (2.3GB)
- **GPU**: NVIDIA GTX 1650 (4GB VRAM)
- **API Endpoint**: `http://tony-omen.local:8001/v1/chat/completions`
- **Context Window**: 4K tokens
- **Status**: Active but overloaded (2944MB/4096MB GPU used, 72%)

### Alternative Model
- **Model**: thai-legal-gemma-4b-cpt.Q4_K_M.gguf (5.0GB)
- **Location**: `/data/gguf/` (available but offline)
- **Specialization**: Thai legal content, better Thai language understanding
- **Status**: **Offline as of 2026-08-06** - Removed from docker-compose alias to save GPU resources
- **Reason**: GPU memory constraints (5GB model vs 4GB available VRAM)

### Model Switching Constraints
- Thai legal model (5GB) exceeds available GPU memory (4GB)
- Removed from docker-compose alias (2026-08-06) to prevent load attempts
- Phi-3-mini (2.3GB) now the only active model
- Context size exceeded errors indicate Phi-3 overload under current request volume
- Thai legal model can be re-enabled by adding back to docker-compose alias if GPU upgraded

### Model Management
```bash
# Check loaded models
curl http://tony-omen.local:8001/v1/models | jq .

# Check GPU memory usage
docker exec thai-legal-inference nvidia-smi

# Check Llama server health
curl http://tony-omen.local:8001/health
```

## Troubleshooting

- `mcp0_list_conversations` / script fails with "No persisted LINE session" → the Yomi MCP server is not pointing at the data dir with the LINE credentials. Check the `mcpServers` config and restart the client.
- Running a second Yomi server on the same `~/.local/share/yomi` while another holds `search-index.db` will block.
- If messages look garbled after a Yomi update, inspect the raw `get_chat_messages` output and adjust the CSV tokenizer in `fetch-conversations.mjs`.
- Process status stuck in "processing" → Check `process-status.json` and clear if needed: `rm /home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/process-status.json`
- Summaries not generating → Check Llama API is accessible at `http://localhost:8001/v1/chat/completions` and GPU is available
- **GPU memory exhaustion** → Phi-3 using 2944MB/4096MB (72%). Thai legal model (5GB) cannot load. Context size exceeded errors indicate model overload. Consider rate limiting or GPU upgrade (2026-08-06).
- Daily summaries empty → Ensure `process-conversations.mjs` includes `generateDailySummaries()` call (added in 2026-08-03 fix). Previously only available in legacy `update-conversations.mjs`.
- Summary language mismatch → Language-aware summarization implemented (2026-08-03) with Thai/English/mixed detection. Some encoding issues remain for certain conversations.
- Frequent Llama API 500 errors → Rate limiting and circuit breakers implemented (2026-08-03) to manage GPU load. Check `/api/yomi/rate-limiter-status` for current state.
- **Yomi API not responding** → Check `yomi-api.service` status: `systemctl status yomi-api.service`. Service auto-restarts on failure (added 2026-08-04).
- **LINE API rate limit (code 103)** → Authentication temporarily restricted. Wait 1-24 hours for restriction to lift, then re-login with `npx @rikaidev/yomi login`. Implement exponential backoff for login retries to prevent future rate limits. (2026-08-06)

## LINE API Rate Limit Management (2026-08-06)

### Rate Limit Code 103
- **Error Message**: `認証が一時的に制限されています。しばらく経ってからもう一度お試してください。`
- **Translation**: "Authentication is temporarily restricted. Please try again later."
- **Cause**: Too many login attempts in short period
- **Duration**: Typically 1-24 hours
- **Impact**: yomi-fetch.timer finds 0 conversations, cannot download new messages

### Mitigation Strategies
1. **Wait for restriction to lift** - Monitor periodically, attempt login every 2 hours
2. **Exponential backoff** - Implement retry logic with increasing delays (1min, 5min, 15min, 1hr, 4hr)
3. **Rate limit detection** - Parse error codes and trigger automatic retry logic
4. **Login attempt throttling** - Limit login attempts to once per hour maximum
5. **Session persistence** - Maintain valid session longer to reduce login frequency

### Implementation Plan
- Add rate limit detection to `fetch-conversations.mjs`
- Implement exponential backoff for login retries
- Add login attempt logging to track frequency
- Monitor session validity and proactively refresh before expiry
- Document LINE API rate limit policies

### Current Status
- **Rate Limit Active**: Yes (2026-08-06)
- **Last Login Attempt**: Failed with code 103
- **Next Action**: Wait for restriction to lift, then re-login
- **Improvement**: LINE API Rate Limit Mitigation added to ssot.improvements.yml
- **Variable daily summary quality** → Some conversations show rich extraction (events/actions/topics) while others have empty arrays despite having messages. Check `/api/yomi/summary-quality` for per-conversation metrics (2026-08-05).
- **Systemd service failure** → If `yomi-api.service` fails but API runs manually, check logs: `journalctl -u yomi-api.service`. May need to restart service or fix configuration (2026-08-05).
- **Database cleanup required** → Some conversations have `last_message_time: null` despite having messages, and duplicate entries with corrupted chat_id fields containing keyMaterial JSON. Use SQL to fix null timestamps and remove duplicates (2026-08-05).

## UI Improvements (Post-Improvement Session)

The Yomi web UI was streamlined for better usability:

### Consolidated Refresh Actions
- Single refresh button in header (previously multiple refresh controls)
- Refresh indicator shows active fetching/processing
- Automatic refresh on page load

### Actions Menu
- Three-dot menu (⋮) for per-conversation actions
- Options: Refresh, Open in new tab, Mark as read
- Cleaner interface with fewer visible buttons

### Collapsible Categories
- Category chips toggle visibility of conversations
- Active filters highlighted with category colors
- Group/ungroup toggle for conversations
- Real-time count updates per category

### Conditional Scroll Controls
- Scroll-to-top button appears only when needed
- Smooth scrolling behavior
- Responsive to viewport changes

## Monitoring Integration

Yomi is integrated into the health check system with comprehensive monitoring:

### Health Check Configuration
- **Yomi API**: Monitored at `http://tony-omen.local:8080/api/yomi/conversations`
- **Yomi Summarization**: Monitored at `http://tony-omen.local:8080/api/yomi/summarization-status`
- **Yomi Rate Limiter**: Monitored at `http://tony-omen.local:8080/api/yomi/rate-limiter-status`
- **Category**: API services
- **Timeout**: 5 seconds
- **Config**: `docs/ssot/infrastructure/ssot.health.home.yml`

### GPU Load Management (2026-08-03, Updated 2026-08-04)
- **Rate Limiting**: Optimized settings (3 concurrent for daily summaries, 1 for regular summaries) to balance speed and GPU load
- **Circuit Breakers**: Automatic protection when GPU overloaded (2-5 failures trigger open state)
- **Queue Management**: Prevents request pile-up with configurable timeouts
- **GPU Monitoring**: Real-time GPU utilization, memory, and temperature tracking
- **Alerting**: Automatic detection of circuit breaker triggers, high GPU load, and temperature issues

### Rate Limiter Status (Updated 2026-08-04)
- **Summary Rate Limiter**: 1 concurrent, 2min queue timeout
- **Daily Rate Limiter**: 3 concurrent, 3min queue timeout (increased from 1 for faster processing)
- **Summary Circuit Breaker**: Opens after 2 failures, 3min timeout
- **Daily Circuit Breaker**: Opens after 5 failures, 4min timeout (more tolerant for batch processing)

### Rate Limiter and Circuit Breaker Architecture

**Implementation File:** `scripts/yomi/llama-rate-limiter.mjs`

**Rate Limiter Class:**
- Tracks running requests and queue depth
- Implements FIFO queue with timeout
- Automatically processes queued requests when slots available
- Returns statistics: running, queued, maxConcurrent

**Circuit Breaker Class:**
- Tracks failure count and last failure time
- Implements state machine (closed → open → half-open → closed)
- Automatic reset on successful requests
- Manual reset capability via API

**Circuit Breaker States:**
- **Closed**: Normal operation, requests pass through
- **Open**: Requests blocked after threshold failures, timeout period active
- **Half-open**: Testing recovery after timeout, allows single request to test

**Integration Points:**
- Process stage wraps Llama API calls with rate limiters
- API server provides `/api/yomi/rate-limiter-status` endpoint
- Health check system monitors rate limiter status

**Rate Limiter Status API Response:**
```json
{
  "summaryRateLimiter": {
    "running": 0,
    "queued": 0,
    "maxConcurrent": 1
  },
  "dailyRateLimiter": {
    "running": 0,
    "queued": 0,
    "maxConcurrent": 3
  },
  "summaryCircuitBreaker": {
    "state": "closed",
    "failureCount": 0,
    "lastFailureTime": null
  },
  "dailyCircuitBreaker": {
    "state": "closed",
    "failureCount": 0,
    "lastFailureTime": null
  }
}
```

## Language Detection System (2026-08-03)

### Detection Algorithm

Yomi automatically detects the language of LINE conversations to provide appropriate summarization:

**Thai Character Detection:**
- Unicode range: U+0E00-U+0E7F (Thai character block)
- Calculates ratio of Thai characters to total characters
- Threshold: > 30% Thai characters = Thai language

**Language Categories:**
- **Thai**: > 30% Thai characters
- **English**: < 10% Thai characters
- **Mixed**: 10-30% Thai characters (Thai/English mix)

### Language-Specific Prompts

**Thai Prompt:**
```
สรุปการสนทนา LINE กับ ${name} เป็นประโยคเดียวสั้นๆ (ไม่เกิน 20 คำ) เน้นหัวข้อหลัก คำถาม หรือการตัดสินใจ

${content}

สรุป:
```

**English Prompt:**
```
Summarize the following LINE conversation with ${name} in one concise sentence (under 20 words). Focus on the main topic, question, or decision.

${content}

Summary:
```

**Mixed Language Prompt:**
```
Summarize the following LINE conversation with ${name} in one concise sentence (under 20 words). Use the same language as the messages (Thai/English mix). Focus on the main topic, question, or decision.

${content}

Summary:
```

### Implementation

**File:** `scripts/yomi/process-conversations.mjs`

**Functions:**
- `detectLanguage(text)`: Analyzes text to determine language
- `detectConversationLanguage(messages)`: Aggregates language detection across all messages
- `getLanguageSpecificPrompt(language, name, lines)`: Returns appropriate prompt based on detected language

**Detection Process:**
1. Extract text content from all messages
2. Count Thai characters (U+0E00-U+0E7F)
3. Calculate Thai character ratio
4. Classify as Thai, English, or Mixed
5. Select appropriate summarization prompt

### Benefits

- **Improved Accuracy**: Language-specific prompts produce better summaries
- **Mixed Language Support**: Handles conversations with both Thai and English
- **Cultural Context**: Thai prompts use culturally appropriate phrasing
- **User Experience**: Summaries match the language of the conversation

### Limitations

- Some encoding issues remain for certain conversations
- Detection based on character count, not semantic analysis
- May misclassify short conversations with few characters
- Mixed language conversations may have inconsistent results

## Batch Daily Summarization (2026-08-03)

### Overview

Daily summarization processes conversation messages grouped by date to extract structured information:

**Structured Output Format:**
```json
{
  "events": ["Event 1", "Event 2"],
  "actions": ["Action 1", "Action 2"],
  "topics": ["Topic 1", "Topic 2"]
}
```

**Database Schema:**
- Table: `daily_summaries`
- Fields: chat_id, date, events (array), actions (array), topics (array), message_count
- Index: chat_id + date for efficient lookups

### Batch Processing Strategy

**Batch Size:** 4 dates per API call
- Reduces Llama API calls by 60-75%
- Processes multiple dates in single request
- Falls back to single-date processing on errors

**Date Range:** Last 30 days
- Reduces processing load by 40-60%
- Focuses on recent activity
- Configurable for different use cases

**Processing Order:**
1. One-on-one conversations (highest priority)
2. Recent conversations (last 30 days)
3. Older conversations (historical data)

### Implementation

**File:** `scripts/yomi/process-conversations.mjs`

**Functions:**
- `groupMessagesByDate(messages)`: Groups messages by date
- `generateDailySummaries(chatId, messages, name)`: Main batch processing function
- `saveDailySummary(chatId, date, events, actions, topics, messageCount)`: Saves to database
- `processSingleDate(chatId, date, dayMessages, name, total, processed)`: Fallback for single dates

**Batch Processing Flow:**
1. Group messages by date
2. Filter to last 30 days
3. Create batch prompts (4 dates each)
4. Submit to Llama API with daily rate limiter
5. Parse structured JSON response
6. Save individual date summaries to database
7. Handle errors with circuit breaker logic

### Daily Summary Prompt

```
Extract structured information from this LINE conversation for each date. Return JSON with date keys and values containing events, actions, and topics arrays.

${messagesByDate}

Return format:
{
  "YYYY-MM-DD": {
    "events": ["event1", "event2"],
    "actions": ["action1", "action2"],
    "topics": ["topic1", "topic2"]
  }
}
```

### Performance Optimizations

**Parallel Processing:**
- Process 3 conversations simultaneously for daily summaries
- Uses daily rate limiter (3 concurrent)
- Balances speed with GPU load

**Selective Processing:**
- Skip dates with < 5 messages
- Skip conversations with < 10 total messages
- Prioritize active conversations

**Error Handling:**
- Circuit breaker prevents cascading failures
- Automatic fallback to single-date processing
- Retry with exponential backoff
- Log errors for troubleshooting

### API Integration

**Endpoint:** `/api/yomi/daily?chat=<id>`
- Returns daily summaries for a conversation
- JSON format with date keys
- Includes message count per date

**Example Response:**
```json
{
  "2026-08-01": {
    "events": ["Meeting scheduled", "Project deadline discussed"],
    "actions": ["Sent email", "Created task"],
    "topics": ["Project management", "Deadlines"]
  },
  "2026-08-02": {
    "events": ["Code review completed"],
    "actions": ["Merged PR", "Updated documentation"],
    "topics": ["Development", "Code review"]
  }
}
```

### Database Integration

**Query for Daily Summaries:**
```sql
SELECT date, events, actions, topics, message_count
FROM daily_summaries
WHERE chat_id = $1
ORDER BY date DESC
```

**Statistics Tracking:**
- Total daily summaries per conversation
- Latest summary date
- Average messages per day
- Coverage percentage (days with summaries / total days)

## GPU Queue Integration (2026-08-04)

### Overview

Yomi integrates with the GPU queue system for managed GPU workload scheduling:

**Job Types:**
- `yomi_summary`: Individual conversation summarization
- `yomi_daily`: Daily summary generation
- Priority level: 2 (medium-high priority)

### Integration Module

**File:** `scripts/yomi/gpu-queue-integration.mjs`

**Functions:**
- `submitSummaryJob(chatId, prompt, type)`: Submit summary job to queue
- `submitDailySummaryJob(chatId, date, prompt, type)`: Submit daily summary job
- `submitBatchDailySummaryJob(chatId, dates, prompt, type)`: Submit batch daily summary job
- `getJob(jobId)`: Check job status
- `updateJobStatus(jobId, status, error)`: Update job completion

### Job Parameters

**Summary Job:**
```json
{
  "chatId": "c123",
  "prompt": "Summarize conversation...",
  "type": "yomi_summary",
  "model": "Phi-3-mini-4k-instruct-q4",
  "maxTokens": 150,
  "temperature": 0.3
}
```

**Daily Summary Job:**
```json
{
  "chatId": "c123",
  "date": "2026-08-01",
  "prompt": "Extract daily summary...",
  "type": "yomi_daily",
  "model": "Phi-3-mini-4k-instruct-q4",
  "maxTokens": 300,
  "temperature": 0.3
}
```

**Batch Daily Summary Job:**
```json
{
  "chatId": "c123",
  "dates": ["2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04"],
  "prompt": "Extract batch daily summaries...",
  "type": "batch_daily_summary",
  "model": "Phi-3-mini-4k-instruct-q4",
  "maxTokens": 600,
  "temperature": 0.3
}
```

### Priority Levels

**GPU Queue Priority Mapping:**
- P4: embedding, yomi_summary, yomi_daily (highest priority)
- P3: txt2vid, cogvideo
- P2: imagen2
- P1: llama (lowest priority)

**Rationale:**
- Yomi workloads are high priority for user-facing features
- Embedding jobs are critical for search functionality
- Image/video generation is lower priority (background work)

### Database Functions

**File:** `scripts/gpu-queue/db.mjs`

**Yomi-Specific Functions:**
- `getJobTypeBreakdown()`: Returns job counts by type and status
- `getRecentJobs(limit)`: Returns recent completed/failed/cancelled jobs
- `getPriorityDistribution()`: Returns pending jobs by priority level

**Job Type Breakdown Response:**
```json
{
  "yomi_summary": {
    "completed": 10,
    "failed": 1,
    "running": 2
  },
  "yomi_daily": {
    "completed": 5,
    "failed": 0,
    "running": 1
  }
}
```

### Integration Benefits

**GPU Load Management:**
- Centralized queue prevents GPU overload
- Priority-based scheduling ensures critical work completes first
- Fair sharing across all GPU workloads

**Monitoring:**
- Job status tracking in health check dashboard
- Historical job data for performance analysis
- Error tracking and retry logic

**Scalability:**
- Easy to add new Yomi job types
- Configurable priority levels
- Support for batch and single jobs

### Current Status

**Implementation Phase:** Ready for integration
- GPU queue integration module created
- Job submission functions implemented
- Database functions for job tracking available
- Priority levels configured

**Next Steps:**
- Replace direct Llama API calls with GPU queue submissions
- Update process-conversations.mjs to use queue
- Add job status polling for completion
- Implement fallback to direct API on queue failures

### Performance Optimizations (2026-08-04)
- **Batch Processing**: Process 4 dates per API call to reduce Llama API calls by 60-75%
- **Selective Processing**: Only generate daily summaries for last 30 days (reduces processing load by 40-60%)
- **Conversation Prioritization**: One-on-one conversations first, then recent (last 30 days), then older
- **Parallel Processing**: Process 3 conversations simultaneously for daily summaries
- **Extended Window**: Processing timer increased from 5min to 10min for more complete cycles
- **GPU Queue Integration**: Ready for integration with existing GPU queue system (priority 2 for Yomi workloads)

## Process Status Tracking

Yomi tracks processing state in a JSON file:

### Status File Location
- **Path**: `/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/process-status.json`
- **Format**: JSON with timestamp
- **Updated by**: `process-conversations.mjs`

### Status Structure
```json
{
  "status": "idle" | "processing",
  "currentChat": "<chatId>",
  "total": <number>,
  "completed": <number>,
  "timestamp": "<ISO8601>"
}
```

### Usage
- Can be manually cleared if stuck
- Available via `/api/yomi/activity-status` for GPU monitor integration
- Can be checked by health check for summarization status

## Backlog Management

### Backlog Assessment Strategy
- Monitor `fetch-data/` directory for stale fetches
- Check `process-status.json` for stuck processing
- Review PostgreSQL for conversations without summaries
- Use `summary_quality` field to identify low-quality summaries

### Clearing Strategy
1. Identify conversations with `summary_quality = 0` or `null`
2. Force re-summarize with `--force` flag
3. Clear summary cache if needed: `rm /home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/summaries.json`
4. Monitor batch processing to avoid overwhelming GPU

## API Endpoints

### Implemented Endpoints (in `yomi-api.mjs`)
- `GET /api/yomi/health` - Health check
- `GET /api/yomi/conversations` - List all conversations
- `GET /api/yomi/messages?chat=<id>` - Get messages for a conversation
- `GET /api/yomi/daily?chat=<id>` - Get daily summaries
- `GET/POST /api/yomi/refresh?chat=<id>` - Manual refresh trigger
- `POST /api/yomi/send` - Send a message
- `GET /api/yomi/media/<chatId>/<messageId>` - Download media
- `GET /api/yomi/last-updated` - Last database update timestamp
- `GET/POST /api/yomi/fetch?chat=<id>` - Trigger fetch stage manually
- `GET/POST /api/yomi/process?chat=<id>&force=<bool>` - Trigger process stage manually
- `GET /api/yomi/activity-status` - Comprehensive system status, GPU status, rate limiter status
- `GET /api/yomi/rate-limiter-status` - Rate limiter and circuit breaker status (GPU monitoring)
- `GET /api/yomi/summarization-status` - Summarization statistics and quality metrics
- `GET /api/yomi/summary-quality` - Detailed quality metrics per conversation
- `POST /api/yomi/resummarize` - Trigger re-summarization of conversations

## URLs

- List: `http://tony-omen.local:8080/apps/yomi/`
- Single chat: `http://tony-omen.local:8080/apps/yomi/chat.html?chat=<chatId>`
- API base: `http://tony-omen.local:8080/api/yomi/`

---

## Tags

- **yomi**: LINE conversation management system
- **architecture**: Two-stage fetch/process pipeline
- **systemd**: Automated timers for fetch (15min) and process (5min)
- **ui**: Streamlined interface with actions menu and collapsible categories
- **monitoring**: Health check integration with GPU monitoring
- **api**: RESTful endpoints for conversations, messages, media
- **postgresql**: Database backend for conversations and messages
- **llama**: AI summarization using Phi-3-mini-4k-instruct-q4
- **backlog**: Strategy for clearing unprocessed conversations
- **process-status**: JSON file tracking processing state
- **rate-limiting**: GPU load management with rate limiters and circuit breakers
- **language-detection**: Thai/English/mixed language detection for summarization
- **daily-summaries**: Batch daily summarization with structured output
- **gpu-queue**: Integration with GPU queue system for workload scheduling
