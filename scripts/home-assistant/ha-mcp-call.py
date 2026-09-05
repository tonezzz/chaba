#!/usr/bin/env python3
"""Call a tool on a Home Assistant MCP endpoint (ha_mcp_tools custom component)."""
import argparse
import asyncio
import json
import sys
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client


def _coerce(value):
    low = value.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low == "null" or low == "none":
        return None
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        pass
    try:
        return json.loads(value)
    except Exception:
        return value


async def call_tool(url, tool, args):
    async with streamable_http_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            try:
                result = await session.call_tool(tool, args)
            except Exception as e:
                return {"ok": False, "error": str(e)}

            text = ""
            if result and result.content:
                for c in result.content:
                    if c and getattr(c, "text", None):
                        text += c.text
            return {"ok": True, "result_text": text, "tool": tool, "args": args}


def main():
    parser = argparse.ArgumentParser(description="Call an ha_mcp_tools tool on tony-dell")
    parser.add_argument("--url", default="http://127.0.0.1:9585/private_B3WMIAChoseTpDS7fwgwRw",
                        help="HA-MCP endpoint URL")
    parser.add_argument("--tool", required=True, help="HA-MCP tool name, e.g. ha_reload_core")
    parser.add_argument("--arg", action="append", default=[], help="key=value argument; repeatable")
    args = parser.parse_args()

    arguments = {}
    for a in args.arg:
        if "=" not in a:
            print(f"Invalid --arg {a}; expected key=value", file=sys.stderr)
            sys.exit(1)
        k, v = a.split("=", 1)
        arguments[k] = _coerce(v)

    outcome = asyncio.run(call_tool(args.url, args.tool, arguments))
    print(json.dumps(outcome, indent=2))
    return 0 if outcome.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
