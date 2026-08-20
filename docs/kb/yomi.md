---
category: operations
---

# Yomi LINE Web App

## What it is

A static web view served from `http://tony-omen.local:8080/apps/yomi/`.
It lists LINE conversations from the Yomi MCP server and lets you click a title to see recent messages. Each conversation also has an `↗` icon that opens a full single-conversation view (`chat.html?chat=<chatId>`) in a new tab.
## Context/Background

Created 2026-08-04 as part of Chaba infrastructure documentation.


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
- Generates AI summaries using Gemini API (gemma-4-31b-it) with language detection (Thai/English/mixed)
- Categorizes conversations
- Generates daily summaries (events, actions, topics per date)
- Updates summaries and categories in PostgreSQL
- Tracks processing status in `process-status.json`
- Runs via systemd timer with flexible scheduling for intermittent PC usage

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
  - `/api/yomi/session-status` - LINE session validation and login attempt tracking
  - `/api/yomi/login` - Trigger LINE login process (POST)

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

## See also

- [Yomi Api](yomi-api.md)
- [Yomi Daily](yomi-daily.md)
- [Yomi Gpu](yomi-gpu.md)
- [Yomi Language](yomi-language.md)
- [Yomi Model](yomi-model.md)
- [Yomi Monitoring](yomi-monitoring.md)
- [Yomi Processing](yomi-processing.md)
- [Yomi Rate Limits](yomi-rate-limits.md)
- [Yomi Systemd](yomi-systemd.md)
- [Yomi Troubleshooting](yomi-troubleshooting.md)
