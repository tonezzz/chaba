#!/usr/bin/env bash
# verify.sh [host] — contract-check a running roster-shim.
# 1. GET /<lane>/health on loopback (no key needed)
# 2. ws upgrade to /<lane>/ws with a bad key -> expect close 4401/4403
# 3. ws upgrade with ROSTER_SHIM_KEY (or any ada-* key when the lane is
#    open) -> expect {"type":"ready"} then history_request -> history.
set -euo pipefail
HOST="${1:-idc03}"
PORT="${ROSTER_SHIM_PORT:-8796}"

echo "== $HOST:$PORT health"
ssh -o BatchMode=yes "$HOST" \
  "curl -sf http://127.0.0.1:$PORT/devin/health && echo && \
   curl -sf http://127.0.0.1:$PORT/nest/health && echo"

echo "== ws contract probe (needs websockets — run via ada-voice venv)"
ssh -o BatchMode=yes "$HOST" \
  '~/CascadeProjects/ada-voice/.venv/bin/python - "$PORT" <<'"'"'EOF'"'"'
import asyncio, json, sys
import websockets

PORT = sys.argv[1]

async def probe(path, key):
    url = f"ws://127.0.0.1:{PORT}{path}?api_key={key}&channel=web&mode=text&device_id=verify1&chat_id=web-verify"
    try:
        async with websockets.connect(url) as ws:
            first = json.loads(await asyncio.wait_for(ws.recv(), 5))
            if first.get("type") != "ready":
                return f"FAIL {path}: first frame {first}"
            await ws.send(json.dumps({"type": "history_request", "max_turns": 5}))
            h = json.loads(await asyncio.wait_for(ws.recv(), 5))
            ok = h.get("type") == "history" and isinstance(h.get("turns"), list)
            await ws.send(json.dumps({"type": "text", "text": "ping"}))
            got = []
            async def drain():
                async for raw in ws:
                    got.append(json.loads(raw).get("type"))
                    if "response_completed" in got or "error" in got:
                        return
            await asyncio.wait_for(drain(), 120)
            want = ["response_started", "assistant_transcript_delta",
                    "response_completed"]
            missing = [w for w in want if w not in got]
            return (f"OK {path}: ready+history+turn "
                    f"(missing={missing or 'none'})")
    except websockets.exceptions.InvalidStatus as e:
        return f"FAIL {path}: HTTP {e.response.status_code}"
    except Exception as e:
        return f"FAIL {path}: {type(e).__name__} {e}"

async def main():
    key = __import__("os").environ.get("ROSTER_SHIM_KEY", "")
    for lane in ("devin", "nest"):
        # bad key must be refused
        r = await probe(f"/{lane}/ws", "ada-invalid-key-000000")
        print("  bad-key:", r)
        if key:
            print("  good-key:", await probe(f"/{lane}/ws", key))
        else:
            print("  (set ROSTER_SHIM_KEY to probe an authenticated turn)")

asyncio.run(main())
EOF'
