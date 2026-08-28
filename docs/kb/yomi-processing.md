---
category: operations
---

# Manual Refreshing

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

