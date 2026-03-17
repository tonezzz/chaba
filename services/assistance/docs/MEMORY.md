# Memory (Hybrid Mode)

Jarvis uses a hybrid memory model:

- **Authoritative (source of truth):** Google Sheets **Memory Sheet** (KV5)
- **Optional index/cache:** Weaviate (used for search/ranking, can be rebuilt)

## Sheets: KV5 schema

Both Memory and Knowledge sheets follow the KV5 schema:

- `key` (string)
- `value` (string)
- `enabled` (bool)
- `scope` (string: `session|user|global`)
- `priority` (number)

Knowledge keys are de-duplicated against memory keys (if a key exists in Knowledge, it is excluded from Memory load).

## How Jarvis answers questions (high level)

When you ask a question over the live WebSocket session, the backend prepares context and then Gemini Live answers.

Jarvis can use:

- **Conversation context** (current WS session)
- **SHEET_MEMORY_CONTEXT**: compact text derived from enabled Memory sheet rows
- **SHEET_KNOWLEDGE_CONTEXT**: compact text derived from enabled Knowledge sheet rows
- **Tools**: deterministic WS tools (system/notes/reminders/gems/memory) and MCP tools

### Default behavior (prompt-augmented)

Most questions are answered directly by Gemini Live using the injected memory/knowledge context blocks.

### Tool-assisted behavior (recommended for scale)

For precise retrieval (or when memory grows large), Gemini can call:

- `memory_search` to fetch matching items
- `memory_list` to see keys

and then answer based on the returned items.

## Writing memory

### Deterministic UI writes

The frontend can write memory explicitly via WS message type `memory`:

```json
{"type":"memory","action":"add","key":"user.preference.language","value":"Thai","scope":"user","priority":10}
```

### Auto-write (Gemini tool calls)

Gemini Live can call `memory_add(...)` to write new memory items.

System sheet switches (sys KV):

- `memory.write.enabled` (default `true`) — master gate for memory writes
- `memory.autowrite.enabled` (default `true`) — gate for model-initiated writes

If disabled, the backend returns a structured error.