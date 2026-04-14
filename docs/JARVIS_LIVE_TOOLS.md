# Jarvis Live API Tools Support

## Overview

The Jarvis Live API now supports **function calling (tools)** in all 4 scenarios. This allows Gemini to execute tools during voice/text conversations.

## Supported Tools

### Built-in Tools (Always Available)

| Tool Name | Description | Example Usage |
|-----------|-------------|---------------|
| `get_current_time` | Get current date and time | "What time is it?" |
| `set_reminder` | Set a reminder | "Remind me to call John in 5 minutes" |

### MCP Tools (Dynamic)

Tools from configured MCP servers are automatically available:
- News tools
- Google Sheets operations
- Custom MCP tools

## How It Works

### 1. Tool Registration

Tools are fetched when Live session starts:

```python
# From jarvis/websocket/session.py
tools = await _get_live_tools()  # MCP + built-in
gemini_tools = _convert_to_gemini_tools(tools)

# Added to LiveConnectConfig
config = types.LiveConnectConfig(
    response_modalities=["AUDIO"],
    tools=gemini_tools,  # <-- Tools registered here
    speech_config=...
)
```

### 2. Function Call Flow

```
User Request → Gemini Live → Function Call → Execute Tool → Result → Gemini → Response
```

1. **User speaks**: "What's the weather?"
2. **Gemini calls tool**: `get_weather(location="Bangkok")`
3. **Backend executes**: Tool runs via `_execute_live_tool()`
4. **Result sent back**: Via `function_response` message
5. **Gemini responds**: "It's 32°C and sunny in Bangkok"

### 3. Message Types

| Direction | Type | Purpose |
|-----------|------|---------|
| WS → Gemini | `text` | User text input |
| WS → Gemini | `audio` | User audio input |
| WS → Gemini | `function_response` | Tool result back to Gemini |
| Gemini → WS | `text` | Assistant text response |
| Gemini → WS | `audio` | Assistant audio response |
| Gemini → WS | `transcript` | Input/output transcription |
| Gemini → WS | `tool_executed` | Notification that tool ran |

## Configuration

### Environment Variables

```bash
# MCP base URL for tool fetching
JARVIS_MCP_BASE_URL=http://mcp-bundle-assistance:3050

# Disable Live API entirely (fallback to REST)
JARVIS_DISABLE_GEMINI_LIVE=false
```

### Adding Custom Tools

Edit `jarvis/websocket/session.py`:

```python
# In _execute_live_tool()
if tool_name == "my_custom_tool":
    return {
        "success": True,
        "result": do_something()
    }
```

## Code Reference

### Key Functions

| Function | Location | Purpose |
|----------|----------|---------|
| `_get_live_tools()` | `session.py:38` | Fetch MCP + built-in tools |
| `_convert_to_gemini_tools()` | `session.py:336` | Convert to Gemini format |
| `_execute_live_tool()` | `session.py:89` | Execute tool by name |
| `_live_configs_for_model()` | `session.py:356` | Create configs with tools |

### Tool Execution in Response Loop

```python
# In _gemini_to_ws_with_session()
func_call = getattr(part, "function_call", None)
if func_call:
    fn_name = getattr(func_call, "name", "")
    fn_args = getattr(func_call, "args", {})
    
    # Execute
    tool_result = await _execute_live_tool(fn_name, fn_args)
    
    # Send back to Gemini
    await session.send_json({
        "type": "function_response",
        "function_response": {
            "name": fn_name,
            "response": tool_result
        }
    })
```

### Function Response Forwarding

```python
# In _ws_to_gemini_with_session()
if mtype == "function_response":
    fn_response = msg.get("function_response")
    await gemini_session.send_realtime_input(
        function_response=types.FunctionResponse(
            name=fn_response["name"],
            response=fn_response["response"]
        )
    )
```

## Testing

### Test Tool Execution

```bash
# Connect to WebSocket
wscat -c ws://localhost:8000/jarvis/ws/live

# Send text that triggers tool
{"type": "text", "text": "What time is it?"}

# Should receive:
# 1. tool_executed message
# 2. Text/audio response with time
```

### Verify Tools in Config

```bash
# Check logs for tool count
docker logs idc1-assistance-core-jarvis-backend-1 | grep "Live API configured with"
```

## Troubleshooting

### Tools Not Available

1. Check MCP connection:
   ```bash
   curl http://localhost:8000/jarvis/api/test-mcp
   ```

2. Verify tools in Live config:
   ```bash
   docker logs ... | grep "configured with"
   ```

### Function Calls Not Executing

1. Check logs for "Live function call received"
2. Verify `_execute_live_tool()` handles the tool name
3. Ensure `function_response` messages are being sent

## See Also

- `jarvis/websocket/session.py` - Full implementation
- `jarvis/mcp/router.py` - MCP tool interface
- `docs/JARVIS_LIVE_SCENARIOS_WIKI.md` - Scenario documentation
