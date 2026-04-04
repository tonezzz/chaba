# Modularization Plan for tools_router.py

## Current State
- `tools_router.py` is 3,898 lines with a single massive `handle_mcp_tool_call` function
- Contains ~50+ tool handlers in one monolithic function
- Difficult to maintain, debug, and extend

## Proposed Structure
Split into toolset modules under `jarvis/tools/`:

```
jarvis/tools/
├── __init__.py           # Exports handle_mcp_tool_call
├── base.py              # Common utilities and deps
├── projects_tools.py    # Projects registry, sheets, proposals
├── system_tools.py      # System reload, macros, skills
├── memo_tools.py        # Memo CRUD operations
├── ui_tools.py          # Time, session, calendar tools
├── mcp_forward_tools.py # MCP forwarding (browser, aim, etc.)
└── pending_tools.py     # Pending write queue operations
```

## Migration Strategy
1. **Phase 1**: Extract utilities to `base.py`
2. **Phase 2**: Create toolset modules with individual handler functions
3. **Phase 3**: Update main router to dispatch to toolset modules
4. **Phase 4**: Add tests and verify functionality

## Benefits
- **Maintainability**: Each toolset ~200-400 lines vs 3,898 lines
- **Debugging**: Isolate issues to specific toolsets
- **Testing**: Unit test individual toolsets
- **Onboarding**: Easier for new developers to understand
- **Risk**: Incremental migration reduces regression risk

## Implementation Details
- Keep same function signatures for compatibility
- Use dependency injection pattern for shared deps
- Preserve all existing error handling and validation
- Maintain WebSocket pending confirmation behavior
- No breaking changes to external API

Would you like me to proceed with Phase 1 (extract utilities)?
