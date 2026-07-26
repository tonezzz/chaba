# Yomi LINE Web App

## What it is

A static web view served from `http://192.168.1.48:8080/apps/yomi/`.
It lists LINE conversations from the Yomi MCP server and lets you click a title to see recent messages. Each conversation also has an `↗` icon that opens a full single-conversation view (`chat.html?chat=<chatId>`) in a new tab.

## Key files

| File | Purpose |
|------|---------|
| `chaba/stacks/web/public/apps/yomi/index.html` | Conversation list, inline message toggle, new-tab icon |
| `chaba/stacks/web/public/apps/yomi/chat.html` | Full single-conversation view |
| `chaba/stacks/web/public/apps/yomi/.gitignore` | Ignores generated `conversations.json` and `messages/` |
| `chaba/scripts/yomi/update-conversations.mjs` | Fetches data from Yomi and writes `conversations.json` + `messages/<chatId>.json` |
| `chaba/stacks/web/Caddyfile` | `handle_path /apps/yomi/*` serves `/srv/public/apps/yomi` |

## Data directory

Yomi stores the LINE session and search index in `~/.local/share/yomi`.
Both the Claude Desktop and Windsurf MCP configs must run `/home/tony/.yomi/mcpb/run.mjs` **without** overriding `YOMI_DATA_DIR` so they share the same session.
Only one Yomi MCP server can hold `search-index.db` at a time.

## Refreshing data

```bash
node /home/tony/CascadeProjects/chaba/scripts/yomi/update-conversations.mjs
```

This script:

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
- If messages look garbled after a Yomi update, inspect the raw `get_chat_messages` output and adjust the CSV tokenizer in `update-conversations.mjs`.

## URLs

- List: `http://192.168.1.48:8080/apps/yomi/`
- Single chat: `http://192.168.1.48:8080/apps/yomi/chat.html?chat=<chatId>`
