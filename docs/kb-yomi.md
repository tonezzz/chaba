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
- Updates summaries and categories in PostgreSQL
- Tracks processing status in `process-status.json`
- Runs every 5 minutes via systemd timer

### API Server (`yomi-api.mjs`)
- HTTP API on port 3000 (default)
- Endpoints:
  - `/api/yomi/health` - Health check
  - `/api/yomi/conversations` - List all conversations
  - `/api/yomi/messages?chat=<id>` - Get messages for a conversation
  - `/api/yomi/daily?chat=<id>` - Get daily summaries
  - `/api/yomi/refresh?chat=<id>` - Manual refresh trigger
  - `/api/yomi/send` - Send a message
  - `/api/yomi/media/<chatId>/<messageId>` - Download media
  - `/api/yomi/last-updated` - Last database update timestamp

### Planned API Endpoints (Not Yet Implemented)
- `/api/yomi/fetch` - Trigger fetch stage manually
- `/api/yomi/process` - Trigger process stage manually
- `/api/yomi/activity-status` - Return processing status from `process-status.json`

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

### Fetch Timer (`yomi-fetch.timer`)
- **Frequency**: Every 15 minutes (`*:0/15`)
- **Service**: `yomi-fetch.service`
- **Location**: `/etc/systemd/system/yomi-fetch.timer`
- **Enabled**: Yes (symlinked in `timers.target.wants`)

### Process Timer (`yomi-process.timer`)
- **Frequency**: Every 5 minutes (`*:0/5`)
- **Service**: `yomi-process.service`
- **Location**: `/etc/systemd/system/yomi-process.timer`
- **Enabled**: Yes (symlinked in `timers.target.wants`)

### Management Commands
```bash
# Check timer status
systemctl list-timers yomi-*

# View timer logs
journalctl -u yomi-fetch.timer
journalctl -u yomi-process.timer

# Manual trigger
systemctl start yomi-fetch.service
systemctl start yomi-process.service
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

## Troubleshooting

- `mcp0_list_conversations` / script fails with "No persisted LINE session" → the Yomi MCP server is not pointing at the data dir with the LINE credentials. Check the `mcpServers` config and restart the client.
- Running a second Yomi server on the same `~/.local/share/yomi` while another holds `search-index.db` will block.
- If messages look garbled after a Yomi update, inspect the raw `get_chat_messages` output and adjust the CSV tokenizer in `fetch-conversations.mjs`.
- Process status stuck in "processing" → Check `process-status.json` and clear if needed: `rm /home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/process-status.json`
- Summaries not generating → Check Llama API is accessible at `http://localhost:8001/v1/chat/completions` and GPU is available

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

Yomi is integrated into the health check system:

### Health Check Configuration
- **Yomi API**: Monitored at `http://tony-omen.local:8080/api/yomi/conversations`
- **Category**: API services
- **Timeout**: 5 seconds
- **Config**: `docs/overview/ssot.health.home.yml`

### GPU Monitor Integration (Planned)
- GPU monitor intended to display Yomi processing status
- Planned endpoint: `/api/yomi/activity-status` (not yet implemented)
- Would show: Processing state, current chat, progress
- Location: `stacks/web/public/apps/gpu-monitor/gpu-monitor.js`
- Current status: Endpoint needs to be added to `yomi-api.mjs`

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
- Intended for GPU monitor integration (pending endpoint implementation)
- Would be checked by health check for summarization status (pending)

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

### Planned Endpoints (Not Yet Implemented)
- `POST /api/yomi/fetch` - Trigger fetch stage manually
- `POST /api/yomi/process` - Trigger process stage manually
- `GET /api/yomi/activity-status` - Return processing status from `process-status.json`

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
- **monitoring**: Health check integration (GPU monitor pending)
- **api**: RESTful endpoints for conversations, messages, media
- **postgresql**: Database backend for conversations and messages
- **llama**: AI summarization using Phi-3-mini-4k-instruct-q4
- **backlog**: Strategy for clearing unprocessed conversations
- **process-status**: JSON file tracking processing state
