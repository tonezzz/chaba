#!/usr/bin/env python3
"""Generic MCP stdio tool-allowlist proxy.

Sits between an MCP client (Devin/Windsurf) and a real stdio MCP server.
Proxies newline-delimited JSON-RPC both ways, but:

  * rewrites ``tools/list`` responses to only tools matching the allowlist
    (fnmatch patterns, so ``"list_*"`` works);
  * answers ``tools/call`` for filtered-out tools directly with a JSON-RPC
    error — filtered tools are NOT passed through to the upstream server.

Allowlist sources (first hit wins):

  1. ``--allowfile PATH`` / ``MCP_ALLOWFILE`` env — JSON file:
       {"command": [...], "env": {...}, "allow": ["list_*", "get_me", ...]}
     ``command``/``env`` are optional in proxy mode (``--`` args win) and
     required for ``--list-only`` when no ``--`` command is given.
     A bare JSON list is also accepted as the allow pattern list.
  2. ``MCP_ALLOW_TOOLS`` env — comma-separated patterns.

Escape hatch (trivially reversible, per mcp-tool-filtering card):
  * set ``MCP_ALLOWLIST_OFF=1`` in the server's env block, or
  * remove/empty the ``allow`` list, or
  * point the mcp_config.json entry back at the original command.
Any of these restores the full upstream tool surface with no code change.

Usage in ~/.config/devin/mcp_config.json:

  "github": {
    "command": "/usr/bin/python3",
    "args": [
      "/home/tony/.config/devin/mcp-scripts/mcp-allowlist.py",
      "--allowfile",
      "/home/tony/.config/devin/mcp-scripts/allowlist.github.json"
    ]
  }

Probe / verify (handshakes the child, prints the filtered tools/list
response as one JSON line, exits):

  MCP_ALLOWFILE=~/.config/devin/mcp-scripts/allowlist.github.json \
      python3 mcp-allowlist.py --list-only
"""

import argparse
import fnmatch
import json
import os
import queue
import subprocess
import sys
import threading

PROTOCOL_VERSION = "2025-03-26"


def _load_spec(allowfile):
    if not allowfile:
        return {}
    path = os.path.expanduser(allowfile)
    if not os.path.isfile(path):
        print(f"[mcp-allowlist] allowfile not found: {path}", file=sys.stderr)
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception as e:
        print(f"[mcp-allowlist] bad allowfile {path}: {e}", file=sys.stderr)
        return {}
    if isinstance(data, list):
        return {"allow": data}
    return data if isinstance(data, dict) else {}


def _patterns(spec):
    pats = spec.get("allow")
    if pats is None:
        env = os.environ.get("MCP_ALLOW_TOOLS", "")
        pats = [p.strip() for p in env.split(",") if p.strip()]
    return [p for p in (pats or []) if isinstance(p, str)]


def _allowed(name, patterns):
    return any(fnmatch.fnmatchcase(name, p) for p in patterns)


class Proxy:
    def __init__(self, cmd, env_extra, patterns):
        if os.environ.get("MCP_ALLOWLIST_OFF") == "1":
            patterns = []
        self.patterns = patterns
        env = dict(os.environ)
        env.update(env_extra or {})
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=None, env=env, text=True, bufsize=1,
        )
        self._out_lock = threading.Lock()

    def _emit(self, obj_or_line):
        line = obj_or_line if isinstance(obj_or_line, str) else json.dumps(obj_or_line)
        with self._out_lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()

    def _filter_tools(self, msg):
        tools = msg.get("result", {}).get("tools")
        if self.patterns and isinstance(tools, list):
            kept = [t for t in tools if _allowed(t.get("name", ""), self.patterns)]
            msg["result"]["tools"] = kept
        return msg

    def _child_reader(self, response_queue=None):
        try:
            while True:
                line = self.proc.stdout.readline()
                if not line:
                    break
                if response_queue is not None:
                    response_queue.put(line)
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    self._emit(line.rstrip("\n"))
                    continue
                self._emit(self._filter_tools(msg))
        finally:
            try:
                self.proc.stdout.close()
            except Exception:
                pass

    def _reject(self, req_id, tool):
        self._emit({
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32601,
                "message": (
                    f"tool '{tool}' is filtered out by the MCP allowlist "
                    "(MCP_ALLOWFILE); set MCP_ALLOWLIST_OFF=1 or edit the "
                    "allowfile to restore it"
                ),
            },
        })

    def serve(self):
        reader = threading.Thread(target=self._child_reader, daemon=True)
        reader.start()
        try:
            for line in iter(sys.stdin.readline, ""):
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    self.proc.stdin.write(line + "\n")
                    self.proc.stdin.flush()
                    continue
                if (
                    self.patterns
                    and msg.get("method") == "tools/call"
                    and not _allowed(msg.get("params", {}).get("name", ""), self.patterns)
                ):
                    self._reject(msg.get("id"), msg["params"].get("name"))
                    continue
                self.proc.stdin.write(json.dumps(msg) + "\n")
                self.proc.stdin.flush()
        finally:
            self._shutdown()

    def list_only(self, timeout=60):
        rq = queue.Queue()
        reader = threading.Thread(target=self._child_reader, args=(rq,), daemon=True)
        reader.start()

        def send(obj):
            self.proc.stdin.write(json.dumps(obj) + "\n")
            self.proc.stdin.flush()

        def wait_for(want_id):
            deadline = threading.Event()
            timer = threading.Timer(timeout, deadline.set)
            timer.start()
            try:
                while not deadline.is_set():
                    try:
                        line = rq.get(timeout=0.5)
                    except queue.Empty:
                        if self.proc.poll() is not None:
                            raise RuntimeError("upstream server exited during handshake")
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("method") == "tools/call" or "method" in msg:
                        continue  # server->client request/notification; skip
                    if msg.get("id") == want_id:
                        return msg
                raise TimeoutError(f"no response to id={want_id} within {timeout}s")
            finally:
                timer.cancel()

        send({
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mcp-allowlist-probe", "version": "1"},
            },
        })
        wait_for(0)
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        resp = wait_for(1)
        self._emit(self._filter_tools(resp))
        self._shutdown()

    def _shutdown(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


def main():
    ap = argparse.ArgumentParser(description="MCP stdio tool-allowlist proxy")
    ap.add_argument("--allowfile", default=os.environ.get("MCP_ALLOWFILE"))
    ap.add_argument("--list-only", action="store_true",
                    help="handshake child, print filtered tools/list, exit")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("cmd", nargs=argparse.REMAINDER,
                    help="-- <upstream server command> (overrides allowfile command)")
    args = ap.parse_args()

    spec = _load_spec(args.allowfile)
    patterns = _patterns(spec)

    cmd = args.cmd
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        cmd = spec.get("command") or []
    if not cmd:
        ap.error("no upstream command: pass '-- <cmd>' or set 'command' in the allowfile")

    proxy = Proxy(cmd, spec.get("env"), patterns)
    try:
        if args.list_only:
            proxy.list_only(timeout=args.timeout)
        else:
            proxy.serve()
    except (TimeoutError, RuntimeError) as e:
        print(f"[mcp-allowlist] {e}", file=sys.stderr)
        proxy._shutdown()
        sys.exit(2)
    except BrokenPipeError:
        proxy._shutdown()


if __name__ == "__main__":
    main()
