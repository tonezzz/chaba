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


async def _run(
    url: str,
    session_id: str,
    timeout_s: float,
    send_text: Optional[str],
    send_json: Optional[dict[str, Any]],
    expect_type: Optional[str],
) -> int:
    ws_url = url
    if "?" in ws_url:
        ws_url = f"{ws_url}&session_id={session_id}"
    else:
        ws_url = f"{ws_url}?session_id={session_id}"

    print(f"connect url={ws_url}")

    state_connected = False
    saw_error: Optional[str] = None
    saw_expected = False

    try:
        async with websockets.connect(ws_url, open_timeout=timeout_s, close_timeout=timeout_s, ping_interval=None) as ws:
            if send_text:
                await ws.send(json.dumps({"type": "text", "text": send_text}))
            if send_json is not None:
                await ws.send(json.dumps(send_json))

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
                    if expect_type == "error":
                        saw_expected = True
                        break
                    saw_error = str(obj.get("message") or "")
                    break

                if expect_type and obj.get("type") == expect_type:
                    saw_expected = True
                    break

                if obj.get("type") == "state" and obj.get("state") == "connected":
                    state_connected = True
                    if not expect_type:
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

    if expect_type and not saw_expected:
        print(f"failed missing_expected_type={expect_type}")
        return 5

    print("ok")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:18018/ws/live")
    ap.add_argument("--session-id", default=str(uuid.uuid4()))
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--send-text", default=None)
    ap.add_argument("--send-json", default=None)
    ap.add_argument("--expect-type", default=None)
    args = ap.parse_args()

    send_json_obj: Optional[dict[str, Any]] = None
    if args.send_json:
        send_json_obj = _as_json(str(args.send_json))
        if send_json_obj is None:
            sys.stderr.write("invalid --send-json (must be a JSON object)\n")
            raise SystemExit(2)

    rc = asyncio.run(
        _run(
            args.url,
            str(args.session_id),
            float(args.timeout),
            args.send_text,
            send_json_obj,
            str(args.expect_type) if args.expect_type else None,
        )
    )
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
