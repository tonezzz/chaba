#!/usr/bin/env python3
# live-check — end-to-end smoke of the gev-gemini voice path.
#
# Connects a client websocket to the bridge (which opens a real Gemini Live
# session), sends a text turn that must produce a tool call, answers the
# function_call with a tool_response, and waits for the model to finish the
# turn. Exercises every hop the browser voice path uses:
#
#   ws connect -> status connected (Gemini session up, tools.json ACCEPTED —
#   an additionalProperties leak would fail the session right here)
#   -> {"type":"text"} -> function_call -> {"type":"tool_response"} -> done
#
#   python3 live-check.py                        # ws://127.0.0.1:8789
#   python3 live-check.py --url wss://host/apps/gev-live/ws
#
# NOTE: each run opens one real Gemini Live session (API quota applies).
# Exit 0 = all checks passed, 1 = a check failed, 2 = could not connect.
import argparse
import asyncio
import json
import sys

try:
    from websockets.asyncio.client import connect
except ImportError:  # older websockets
    from websockets import connect

PROMPT = "Zoom all the way out to the whole-earth globe view."
TIMEOUT = 30
checks = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    checks.append(bool(ok))


async def wait_type(ws, wanted, timeout=TIMEOUT):
    """Return the first message whose .type is in `wanted`; None on timeout."""
    try:
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout)
            msg = json.loads(raw)
            t = msg.get("type")
            print(f"  <- {t}: {json.dumps(msg)[:160]}")
            if t in wanted:
                return msg
            if t == "error":
                return msg
    except (asyncio.TimeoutError, TimeoutError):
        return None


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:8789")
    ap.add_argument("--prompt", default=PROMPT)
    args = ap.parse_args()

    print(f"connecting {args.url}")
    try:
        ws = await asyncio.wait_for(connect(args.url), 15)
    except Exception as e:
        print(f"tools-check live: could not connect: {e}")
        return 2

    async with ws:
        status = await wait_type(ws, {"status", "error"}, 30)
        check("session connected (Gemini Live up, tools.json accepted)",
              bool(status and status.get("type") == "status"),
              json.dumps(status)[:120] if status else "timeout")
        if not status or status.get("type") != "status":
            return 1

        await ws.send(json.dumps({"type": "text", "text": args.prompt}))
        print(f"  -> text: {args.prompt}")
        call = await wait_type(ws, {"function_call", "done", "error"}, TIMEOUT)
        check("text turn produced function_call",
              bool(call and call.get("type") == "function_call"),
              f"name={call.get('name')} args={call.get('args')}" if call else "timeout")
        if not call or call.get("type") != "function_call":
            return 1

        resp = {"type": "tool_response", "responses": [{
            "id": call.get("id", ""),
            "name": call.get("name", ""),
            "response": {"ok": True, "result": "simulated by live-check"},
        }]}
        await ws.send(json.dumps(resp))
        print(f"  -> tool_response for {call.get('name')} ({call.get('id')})")
        follow = await wait_type(ws, {"function_call", "done", "error"}, TIMEOUT)
        check("model accepted tool_response and continued the turn",
              bool(follow and follow.get("type") in ("function_call", "done")),
              follow.get("type") if follow else "timeout")
    return 0 if all(checks) and checks else 1


if __name__ == "__main__":
    rc = asyncio.run(main())
    print(f"live-check: {'PASS' if rc == 0 else 'FAIL'}")
    sys.exit(rc)
