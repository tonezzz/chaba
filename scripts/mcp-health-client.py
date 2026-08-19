#!/usr/bin/env python3
"""One-shot MCP client for mcp-health. Runs the server over stdio, calls a tool, prints the JSON result, and exits."""
import json
import os
import shutil
import subprocess
import sys
import threading
import time

SERVER = "/home/tony/CascadeProjects/chaba/mcp/mcp-health/server.js"
CWD = "/home/tony/CascadeProjects/chaba"
NODE = os.environ.get("NODE_BIN") or shutil.which("node") or "/home/tony/.n/bin/node"
INIT_TIMEOUT = 15
CALL_TIMEOUT = 60


def main():
    tool = sys.argv[1] if len(sys.argv) > 1 else "get_health_score"
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}

    env = os.environ.copy()
    env["HEALTH_PROFILE"] = env.get("HEALTH_PROFILE", "home")
    env["HEALTH_CONFIG"] = env.get("HEALTH_CONFIG", os.path.join(CWD, "docs/ssot/infrastructure/ssot.health.yml"))
    env["POSTGRES_HOST"] = env.get("POSTGRES_HOST", "tony-dell")
    env["POSTGRES_PORT"] = env.get("POSTGRES_PORT", "5432")

    proc = subprocess.Popen(
        [NODE, SERVER],
        cwd=CWD,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    pending = {}
    results = {}
    lock = threading.Lock()

    def reader():
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg_id = msg.get("id")
            with lock:
                if msg_id is not None and msg_id in pending:
                    results[msg_id] = msg.get("result") or msg
                    pending[msg_id] = False

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    def send(method, params, req_id=None):
        req_id = req_id or (len(pending) + 1)
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        with lock:
            pending[req_id] = True
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()
        return req_id

    def wait_for(req_id, timeout=INIT_TIMEOUT):
        start = time.time()
        while time.time() - start < timeout:
            with lock:
                if req_id in results:
                    return results.pop(req_id)
            time.sleep(0.1)
        return None

    # Initialize the session
    init_id = send("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "mcp-health-client", "version": "1.0"}
    })
    wait_for(init_id)

    # Notify initialized
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
    proc.stdin.flush()

    # Call the tool
    call_id = send("tools/call", {"name": tool, "arguments": args})
    result = wait_for(call_id, timeout=CALL_TIMEOUT)

    proc.stdin.close()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.terminate()
        proc.wait(timeout=5)

    if result is None:
        print(json.dumps({"error": "timeout or no response from mcp-health"}), file=sys.stderr)
        sys.exit(1)

    if result and result.get("isError"):
        print(json.dumps({"error": result.get("content", [{}])[0].get("text", "unknown")}), file=sys.stderr)
        sys.exit(1)

    text = result.get("content", [{}])[0].get("text", "{}")
    try:
        data = json.loads(text)
        print(json.dumps(data, indent=2))
    except json.JSONDecodeError:
        print(text)


if __name__ == "__main__":
    main()
