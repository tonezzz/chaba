#!/usr/bin/env python3
"""MCP server for rview media viewer."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import views


def _send(message):
    print(json.dumps(message), flush=True)


def handle_initialize(id_):
    return {
        "jsonrpc": "2.0",
        "id": id_,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mcp-rview", "version": "1"},
        },
    }


def _tool(name, description, schema):
    return {"name": name, "description": description, "inputSchema": schema}


def handle_tools_list(id_):
    tools = [
        _tool(
            "rview_list_views",
            "List all rview sessions/views.",
            {"type": "object", "properties": {}},
        ),
        _tool(
            "rview_create_view",
            "Create a new view session.",
            {
                "type": "object",
                "properties": {
                    "view_id": {"type": "string"},
                    "display_name": {"type": "string"},
                },
                "required": ["view_id"],
            },
        ),
        _tool(
            "rview_show",
            "Show media, HTML, or a URL in a view. For raw HTML set media_type to html and provide content (or url as fallback). Only use URLs you are certain are reachable.",
            {
                "type": "object",
                "properties": {
                    "view_id": {"type": "string"},
                    "url": {"type": "string"},
                    "title": {"type": "string"},
                    "media_type": {
                        "type": "string",
                        "enum": ["auto", "image", "video", "audio", "iframe", "pdf", "html"],
                        "default": "auto",
                    },
                    "content": {"type": "string", "description": "Raw HTML content when media_type is html"},
                    "enqueue": {"type": "boolean", "default": False},
                },
                "required": ["view_id", "url"],
            },
        ),
        _tool(
            "rview_queue",
            "Set or append to a view's playlist. Each item may have url, title, media_type, and content (for html).",
            {
                "type": "object",
                "properties": {
                    "view_id": {"type": "string"},
                    "items": {"type": "array", "items": {"type": "object"}},
                    "mode": {
                        "type": "string",
                        "enum": ["replace", "append"],
                        "default": "replace",
                    },
                },
                "required": ["view_id", "items"],
            },
        ),
        _tool(
            "rview_control",
            "Control playback for a view.",
            {
                "type": "object",
                "properties": {
                    "view_id": {"type": "string"},
                    "action": {
                        "type": "string",
                        "enum": [
                            "play",
                            "pause",
                            "stop",
                            "next",
                            "prev",
                            "seek",
                            "volume",
                            "fullscreen",
                            "loop",
                            "shuffle",
                            "slideshow",
                            "stop_slideshow",
                            "clear_queue",
                        ],
                    },
                    "value": {},
                },
                "required": ["view_id", "action"],
            },
        ),
        _tool(
            "rview_status",
            "Get the current state of a view.",
            {
                "type": "object",
                "properties": {"view_id": {"type": "string"}},
                "required": ["view_id"],
            },
        ),
        _tool(
            "rview_delete_view",
            "Delete a view session.",
            {
                "type": "object",
                "properties": {"view_id": {"type": "string"}},
                "required": ["view_id"],
            },
        ),
    ]
    return {"jsonrpc": "2.0", "id": id_, "result": {"tools": tools}}


def handle_tools_call(id_, params):
    name = params.get("name")
    arguments = params.get("arguments", {})
    try:
        if name == "rview_list_views":
            result = views.list_views()
        elif name == "rview_create_view":
            result = views.create_view(
                arguments["view_id"], arguments.get("display_name")
            )
        elif name == "rview_show":
            result = views.show(
                arguments["view_id"],
                arguments["url"],
                title=arguments.get("title"),
                media_type=arguments.get("media_type", "auto"),
                enqueue=arguments.get("enqueue", False),
                content=arguments.get("content"),
            )
        elif name == "rview_queue":
            result = views.queue(
                arguments["view_id"],
                arguments.get("items", []),
                mode=arguments.get("mode", "replace"),
            )
        elif name == "rview_control":
            result = views.control(
                arguments["view_id"],
                arguments["action"],
                value=arguments.get("value"),
            )
        elif name == "rview_status":
            result = views.status(arguments["view_id"])
        elif name == "rview_delete_view":
            result = views.delete_view(arguments["view_id"])
        else:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": id_,
                    "error": {"code": -32602, "message": f"unknown tool: {name}"},
                }
            )
            return
    except Exception as e:
        _send({"jsonrpc": "2.0", "id": id_, "error": {"code": -32603, "message": str(e)}})
        return
    _send(
        {
            "jsonrpc": "2.0",
            "id": id_,
            "result": {"content": [{"type": "text", "text": json.dumps(result, default=str)}]},
        }
    )


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        id_ = msg.get("id")
        if method == "initialize":
            _send(handle_initialize(id_))
        elif method == "tools/list":
            _send(handle_tools_list(id_))
        elif method == "tools/call":
            handle_tools_call(id_, msg.get("params", {}))


if __name__ == "__main__":
    main()
