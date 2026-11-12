#!/usr/bin/env python3
"""board-cli — one-call Kanban mutations via board-api (KNB-1104).

Replaces `ssh idc03 'curl -X POST 127.0.0.1:8787/...'` heredocs with a
typed CLI. Read ops and write ops both supported; board-api remains the
single write door.

Usage:
  board-cli.py get CARDS_ID [--column COL] [--limit N]
  board-cli.py card --id X --title T [--column backlog] [--priority high]
             [--brief B] [--spec S] [--program P] [--tag a,b] [--set k=v ...]
  board-cli.py comment CARD_ID "text" [--from devin]
  board-cli.py action CARD_ID move COLUMN [--from devin]
  board-cli.py request CARD_ID "text" [--options a|b|c] [--from devin]
  board-cli.py respond CARD_ID REQUEST_ID "answer" [--from devin]

Transport: BOARD_API env (default http://127.0.0.1:8787) or --ssh HOST
which pipes the same HTTP call through `ssh HOST curl` (board-api binds
localhost on idc03).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request

API = os.environ.get("BOARD_API", "http://127.0.0.1:8787")


REMOTE_SCRIPT = "~/CascadeProjects/chaba/scripts/board/board-cli.py"


def call(method: str, path: str, payload: dict | None,
         ssh_host: str | None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    if ssh_host:
        # board-api binds localhost on the remote host; the same script
        # exists there via chaba-repo-sync. JSON envelope on stdin avoids
        # shell mangling of '&' in query strings.
        env = json.dumps({"method": method, "path": path,
                          "payload": payload}).encode()
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
             ssh_host, "python3", REMOTE_SCRIPT, "__api"],
            input=env, capture_output=True, timeout=90)
        if r.returncode:
            raise RuntimeError(
                (r.stderr or r.stdout or b"ssh failed").decode()[:300])
        return json.loads(r.stdout or "{}")
    req = urllib.request.Request(
        API + path, data=body, method=method,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or "{}")


def api_mode() -> int:
    """__api — raw board-api call on localhost. stdin carries a JSON
    envelope {method, path, payload}; response JSON on stdout. Used by
    the --ssh transport (keeps '&' in query strings intact)."""
    try:
        env = json.loads(sys.stdin.buffer.read() or b"{}")
    except json.JSONDecodeError:
        env = {}
    method = env.get("method") or "GET"
    path = env.get("path") or "/cards"
    payload = env.get("payload")
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        "http://127.0.0.1:8787" + path, data=body, method=method,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            sys.stdout.write(r.read().decode() or "{}")
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:300]}))
        return 2


def main() -> int:
    # hidden raw-API mode used by --ssh transport
    if len(sys.argv) >= 2 and sys.argv[1] == "__api":
        return api_mode()
    ap = argparse.ArgumentParser()
    ap.add_argument("--ssh", default=None,
                    help="run the API call on this host (e.g. idc03)")
    ap.add_argument("--api", default=None, help="override BOARD_API")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("get")
    g.add_argument("id", nargs="?")
    g.add_argument("--column")
    g.add_argument("--limit", type=int, default=50)

    c = sub.add_parser("card")
    c.add_argument("--id", required=True)
    c.add_argument("--title", required=True)
    c.add_argument("--column", default="backlog")
    c.add_argument("--priority", default="medium")
    c.add_argument("--brief", default="")
    c.add_argument("--spec", default="")
    c.add_argument("--program", default="")
    c.add_argument("--tag", action="append", default=[])
    c.add_argument("--set", action="append", default=[],
                   metavar="K=V", help="extra card fields")

    cm = sub.add_parser("comment")
    cm.add_argument("id")
    cm.add_argument("text")
    cm.add_argument("--from", dest="frm", default="devin")

    ac = sub.add_parser("action")
    ac.add_argument("id")
    ac.add_argument("do", choices=["move", "claim", "release", "close"])
    ac.add_argument("column", nargs="?")
    ac.add_argument("--from", dest="frm", default="devin")

    rq = sub.add_parser("request")
    rq.add_argument("id")
    rq.add_argument("text")
    rq.add_argument("--options", default="")
    rq.add_argument("--from", dest="frm", default="devin")

    rs = sub.add_parser("respond")
    rs.add_argument("id")
    rs.add_argument("request_id")
    rs.add_argument("text")
    rs.add_argument("--from", dest="frm", default="devin")

    args = ap.parse_args()
    if args.api:
        global API
        API = args.api
    ssh = args.ssh

    try:
        if args.cmd == "get":
            qs = f"?limit={args.limit}"
            if args.id:
                qs += f"&id={args.id}"
            if args.column:
                qs += f"&column={args.column}"
            out = call("GET", f"/cards{qs}", None, ssh)
        elif args.cmd == "card":
            payload = {"id": args.id, "title": args.title,
                       "column": args.column, "priority": args.priority,
                       "brief": args.brief, "spec": args.spec,
                       "program": args.program,
                       "tags": args.tag}
            for kv in args.set:
                k, _, v = kv.partition("=")
                payload[k] = v
            out = call("POST", "/card", payload, ssh)
        elif args.cmd == "comment":
            out = call("POST", "/comment",
                       {"id": args.id, "from": args.frm,
                        "text": args.text}, ssh)
        elif args.cmd == "action":
            out = call("POST", "/action",
                       {"id": args.id, "from": args.frm, "do": args.do,
                        "column": args.column}, ssh)
        elif args.cmd == "request":
            out = call("POST", "/request",
                       {"id": args.id, "from": args.frm,
                        "ask": args.text,
                        "options": args.options.split("|")
                        if args.options else []}, ssh)
        else:
            out = call("POST", "/respond",
                       {"id": args.id, "request_id": args.request_id,
                        "from": args.frm, "answer": args.text}, ssh)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:300]}))
        return 2
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
