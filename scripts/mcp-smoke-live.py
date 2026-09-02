#!/usr/bin/env python3
"""Live MCP smoke test: start the mcp_debug server and make a real tool call."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PYTHONPATH = str(REPO / "scripts")


def rpc_call(proc, method, params=None, req_id=None):
    msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        msg["params"] = params
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError(f"no response for {method}")
    return json.loads(line)


def main():
    env = os.environ.copy()
    env["PYTHONPATH"] = PYTHONPATH

    err_fd, err_path = tempfile.mkstemp(suffix=".log")
    os.close(err_fd)
    err_f = open(err_path, "w")

    proc = subprocess.Popen(
        [sys.executable, "-m", "mcp_debug.server"],
        cwd=REPO,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=err_f,
        text=True,
    )

    try:
        init = rpc_call(proc, "initialize", {}, 1)
        assert init["result"]["protocolVersion"] == "2024-11-05", init

        tools = rpc_call(proc, "tools/list", {}, 2)
        names = [t["name"] for t in tools["result"]["tools"]]
        assert "mcp_read_ssot" in names, names

        result = rpc_call(
            proc,
            "tools/call",
            {"name": "mcp_read_ssot", "arguments": {"path": "docs/ssot/ssot.index.yml", "limit": 200}},
            3,
        )
        content = result["result"]["content"][0]["text"]
        assert '"ok":true' in content, content[:200]
        assert "SSOT Index" in content, content[:200]

        print(f"OK: initialize, tools/list ({len(names)} tools), mcp_read_ssot live call passed")
    except Exception as e:
        proc.stdin.close()
        proc.wait(timeout=5)
        err_f.close()
        stderr = Path(err_path).read_text() if Path(err_path).exists() else ""
        print(f"FAIL: {e}", file=sys.stderr)
        if stderr:
            print(stderr, file=sys.stderr)
        sys.exit(1)
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        try:
            err_f.close()
        except Exception:
            pass
        if Path(err_path).exists():
            os.unlink(err_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
