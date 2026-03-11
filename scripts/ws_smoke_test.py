import argparse
import asyncio
import json
import sys
import uuid
from typing import Any, Optional

import websockets


def _as_json(s: str) -> Optional[dict[str, Any]]:
    try:
        obj = json.loads(s)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


async def _run(url: str, session_id: str, timeout_s: float, send_text: Optional[str]) -> int:
    ws_url = url
    if "?" in ws_url:
        ws_url = f"{ws_url}&session_id={session_id}"
    else:
        ws_url = f"{ws_url}?session_id={session_id}"

    print(f"connect url={ws_url}")

    state_connected = False
    saw_error: Optional[str] = None

    try:
        async with websockets.connect(ws_url, open_timeout=timeout_s, close_timeout=timeout_s, ping_interval=None) as ws:
            if send_text:
                await ws.send(json.dumps({"type": "text", "text": send_text}))

            deadline = asyncio.get_event_loop().time() + timeout_s
            while asyncio.get_event_loop().time() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - asyncio.get_event_loop().time()))
                except asyncio.TimeoutError:
                    break

                if isinstance(msg, (bytes, bytearray)):
                    try:
                        msg = msg.decode("utf-8", errors="replace")
                    except Exception:
                        msg = str(msg)

                print(f"recv {msg}")
                obj = _as_json(str(msg))
                if not obj:
                    continue

                if obj.get("type") == "error":
                    saw_error = str(obj.get("message") or "")
                    break

                if obj.get("type") == "state" and obj.get("state") == "connected":
                    state_connected = True
                    break

            try:
                await ws.send(json.dumps({"type": "close"}))
            except Exception:
                pass

    except Exception as e:
        print(f"connect_failed error={e!r}")
        return 2

    if saw_error:
        print(f"failed backend_error={saw_error}")
        return 3

    if not state_connected:
        print("failed missing_state_connected")
        return 4

    print("ok")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:18018/ws/live")
    ap.add_argument("--session-id", default=str(uuid.uuid4()))
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--send-text", default=None)
    args = ap.parse_args()

    rc = asyncio.run(_run(args.url, str(args.session_id), float(args.timeout), args.send_text))
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
