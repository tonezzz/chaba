#!/usr/bin/env python3
"""consumer-canary — standing retired-hostname audit of LIVE surfaces.

OPS-0755 / verify-by-surface duty (AGENTS.md). Producers get health-checked;
consumers don't — this greps the deployed artifacts a user surface actually
loads (card JS, caddy configs, unit envs, HA dashboards) for retired hostnames.

Runs on idc03, ssh's out to hosts. Findings are commented on the canary card
via board-api; a clean run is stdout-only (no card spam).

Env:
  RETIRED_HOSTS   comma list (default tony-dell.taila0626a.ts.net)
  CANARY_CARD     board-api card id to comment on
  BOARD_API       board-api base (default http://127.0.0.1:8787)
"""
import json
import os
import re
import subprocess
import sys
import urllib.request

RETIRED = [h.strip() for h in os.environ.get(
    "RETIRED_HOSTS", "tony-dell.taila0626a.ts.net").split(",") if h.strip()]
PAT = "|".join(re.escape(h) for h in RETIRED)
CARD_ID = os.environ.get(
    "CANARY_CARD", "consumer-canary-standing-retired-hostnam-6aa4a2")
BOARD_API = os.environ.get("BOARD_API", "http://127.0.0.1:8787")
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=8"]

# Matches that are not live consumers — comments, repo-owner names, DNS
# aliases, hostname allow-lists (server-side, not client dials), and
# generated prose JSON (report/event bodies quote hostnames as text).
IGNORE = re.compile("|".join([
    r"github\.com/tony-dell",
    r"--add-host=\S*tony-dell",
    r"AddHost=\S*tony-dell",
    r"ACC_SECRET_HOSTS",
    r"VCAST_REDEEM_HOSTS",
    r"(chaba-report|chaba-events)\.json:",
    r"\.bak[-\w.]*:",          # grep hits inside .bak files
]))
# comment markers — checked AFTER stripping grep's file:line: prefix
COMMENT = re.compile(r"^\s*(#|//|\*)")


def is_ignored(grep_line: str) -> bool:
    if IGNORE.search(grep_line):
        return True
    # strip grep prefix — path:N:, path-N:, or bare N: (single-file -n)
    body = re.sub(r"^([^:\s]+[:-])?\d+:", "", grep_line)
    return bool(COMMENT.match(body))

GREPS = [
    ("omen:tony-ha www", "tony-omen",
     "grep -rInE '%s' ~/.config/home-assistant/www/ 2>/dev/null"),
    ("omen:ada-ha www", "tony-omen",
     "grep -rInE '%s' ~/.config/ada-ha/www/ 2>/dev/null"),
    ("omen:units", "tony-omen",
     "grep -rInE '%s' ~/.config/systemd/user/ ~/.config/containers/systemd/ 2>/dev/null"),
    ("idc02:caddy-edge", "idc02",
     "grep -nE '%s' ~/.config/caddy/Caddyfile 2>/dev/null"),
    ("idc02:web-origin", "idc02",
     "grep -nE '%s' ~/web-srv/caddy/Caddyfile 2>/dev/null"),
    ("idc02:units", "idc02",
     "grep -rInE '%s' ~/.config/systemd/user/ ~/.config/containers/systemd/ 2>/dev/null"),
    ("idc03:units", None,
     "grep -rInE '%s' ~/.config/systemd/user/ ~/.config/containers/systemd/ 2>/dev/null"),
    ("con01:units", "con01",
     "grep -rInE '%s' ~/.config/systemd/user/ ~/.config/containers/systemd/ 2>/dev/null"),
    ("mn01:caddy+units", "mn01",
     "grep -nE '%s' ~/.config/caddy/Caddyfile.mn01 2>/dev/null;"
     "grep -rInE '%s' ~/.config/systemd/user/ ~/.config/containers/systemd/ 2>/dev/null"),
]

# Remote dashboard scan — runs on omen where the HA tokens live. Lists every
# lovelace dashboard per instance and greps config JSON for retired hosts.
DASH_SCAN = r"""
import json, asyncio, os, re
import websockets
pat = re.compile(os.environ["CANARY_HOSTS"])

def tok(path):
    try:
        for l in open(os.path.expanduser(path)):
            if l.startswith("HA_LONG_LIVED_TOKEN="):
                return l.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    return ""

async def scan(port, token, label):
    if not token:
        print(f"SKIP {label}: no token"); return
    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}/api/websocket") as ws:
            await ws.recv()
            await ws.send(json.dumps({"type":"auth","access_token":token}))
            if json.loads(await ws.recv())["type"] != "auth_ok":
                print(f"SKIP {label}: auth failed"); return
            await ws.send(json.dumps({"id":1,"type":"lovelace/dashboards/list"}))
            d = json.loads(await ws.recv())
            dashes = [x.get("url_path") for x in d.get("result",[])]
            for i, dash in enumerate(dashes, 10):
                await ws.send(json.dumps({"id":i,"type":"lovelace/config","url_path":dash}))
                r = json.loads(await ws.recv())
                cfg = json.dumps(r.get("result"))
                for m in pat.finditer(cfg):
                    s = max(0, m.start()-70)
                    print(f"HIT {label}/{dash}: ...{cfg[s:m.end()+50]}")
    except Exception as e:
        print(f"SKIP {label}: {e}")

async def main():
    await scan(8123, tok("~/.config/secrets/home-assistant-token.env"), "tony-ha")
    await scan(8125, tok("~/.config/secrets/ada-ha-token.env"), "ada-ha")

asyncio.run(main())
"""


def run(cmd, host=None):
    full = (["ssh", *SSH_OPTS, host, cmd] if host
            else ["bash", "-c", cmd])
    try:
        r = subprocess.run(full, capture_output=True, text=True, timeout=60)
        return r.stdout
    except subprocess.TimeoutExpired:
        return f"TIMEOUT {cmd[:60]}\n"


def main():
    findings, skips = [], []
    for label, host, tmpl in GREPS:
        cmd = tmpl % ((PAT,) * tmpl.count("%s"))
        out = run(cmd, host)
        for line in out.splitlines():
            if not line.strip() or is_ignored(line):
                continue
            findings.append(f"{label}: {line.strip()[:200]}")

    r = subprocess.run(
        ["ssh", *SSH_OPTS, "tony-omen", f"CANARY_HOSTS='{PAT}' python3 -"],
        input=DASH_SCAN, capture_output=True, text=True, timeout=120)
    for line in r.stdout.splitlines():
        if line.startswith("HIT"):
            findings.append(line[:240])
        elif line.startswith(("SKIP", "TIMEOUT")):
            skips.append(line.strip())

    if not findings:
        print(f"consumer-canary: CLEAN ({len(GREPS)} greps + dashboards)"
              + (f" | skips: {'; '.join(skips)}" if skips else ""))
        return 0

    text = ("[consumer-canary] live retired-host refs found "
            f"({len(findings)}):\n" + "\n".join(f"- {f}" for f in findings[:40])
            + ("\n(skips: " + "; ".join(skips) + ")" if skips else ""))
    print(text)
    try:
        body = json.dumps({"id": CARD_ID, "from": "devin", "text": text}).encode()
        req = urllib.request.Request(
            f"{BOARD_API}/comment", data=body,
            headers={"Content-Type": "application/json"})
        resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
        print("board-api:", resp.get("message"))
    except Exception as e:
        print(f"board-api comment failed: {e}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
