#!/usr/bin/env python3
"""kanban-notify — TG notify on kanban card state changes.

Watches the served checkout's cards dir via git: each tick, diffs the
commits since the last-processed SHA, extracts per-card state changes
(column moves, new cards, requests added/answered, comms) and pushes
one TG message per card through board_notify (default: tg channel,
ada-ha group — same wiring as nest-queue-watch).

Intended as a dispatcher job (every: 5m) on idc03 — the writer host,
whose git log carries every card mutation (board-api writes AND
producer file-writes alike).

Kill switch: touch ~/.config/kanban-notify.off — every tick exits
silently while it exists; rm to resume. Or KANBAN_NOTIFY=off in env.

Env:
  KANBAN_NOTIFY           off disables (default on)
  KANBAN_NOTIFY_STATE     state file, default
                          ~/.local/state/kanban-notify.json
  KANBAN_NOTIFY_OFF_FILE  kill-switch path, default
                          ~/.config/kanban-notify.off
  KANBAN_NOTIFY_REPO      checkout path, default
                          ~/CascadeProjects/chaba-tony-dell
  KANBAN_NOTIFY_CARDS     cards dir rel to repo, default
                          docs/ssot/kanban/cards
  BOARD_NOTIFY_CHANNEL    board_notify channel (default tg)
  BOARD_NOTIFY_TG_CHAT_ID ada-ha group when set (else Tony DM)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
STATE = Path(os.environ.get(
    "KANBAN_NOTIFY_STATE", HOME / ".local/state/kanban-notify.json"))
OFF_FILE = Path(os.environ.get(
    "KANBAN_NOTIFY_OFF_FILE", HOME / ".config/kanban-notify.off"))
REPO = os.environ.get(
    "KANBAN_NOTIFY_REPO", str(HOME / "CascadeProjects/chaba-tony-dell"))
CARDS = os.environ.get("KANBAN_NOTIFY_CARDS", "docs/ssot/kanban/cards")
CARDS_DIR = Path(REPO) / CARDS
MAX_PER_TICK = 5      # don't burst-notify a 15-min commit backlog

sys.path.insert(0, str(Path(__file__).resolve().parent / ".." / "board"))
import board_notify  # noqa: E402


def git(*args: str) -> str:
    r = subprocess.run(["git", "-C", REPO, *args],
                       capture_output=True, text=True, timeout=60)
    return r.stdout.strip()


def card_state(text: str) -> dict:
    """The state fields we care about, from a card file's text."""
    def grab(pat: str) -> str:
        m = re.search(pat, text, re.M)
        return m.group(1).strip() if m else ""
    title = grab(r"^title:\s*(.+)")
    column = grab(r"^column:\s*(.+)")
    reqs = len(re.findall(r"^\- id:\s*[A-Za-z0-9_-]+", text, re.M))
    reqs_done = len(re.findall(r"^  status:\s*(answered|done|closed)\s*$",
                               text, re.M))
    comms = len(re.findall(r"^\- (?:at|ts):", text, re.M))
    return {"title": title, "column": column,
            "reqs": reqs, "reqs_done": reqs_done, "comms": comms}


def summarize(name: str, old: dict | None, new: dict) -> str:
    t = new["title"] or name
    if old is None:
        return f"new card '{t}' ({new['column']})"
    bits = []
    if old["column"] != new["column"]:
        bits.append(f"{old['column']}→{new['column']}")
    dc = new["comms"] - old["comms"]
    if dc > 0:
        bits.append(f"+{dc} comms")
    dr = new["reqs"] - old["reqs"]
    if dr > 0:
        bits.append(f"+{dr} request(s)")
    if new["reqs_done"] > old["reqs_done"]:
        bits.append("request answered")
    if not bits:
        bits.append("updated")
    return f"'{t}': {', '.join(bits)}"


def main() -> int:
    if os.environ.get("KANBAN_NOTIFY") == "off" or OFF_FILE.exists():
        return 0
    if not CARDS_DIR.is_dir():
        print(f"kanban-notify: no cards dir {CARDS_DIR}", file=sys.stderr)
        return 0
    head = git("rev-parse", "HEAD")
    if not head:
        return 0
    last = ""
    try:
        last = json.loads(STATE.read_text()).get("last_sha", "")
    except Exception:
        pass
    if not last:
        # first tick — record position, don't replay history
        STATE.write_text(json.dumps({"last_sha": head}))
        return 0
    if last == head:
        return 0
    shas = git("log", "--format=%H", "--reverse", f"{last}..HEAD").split()
    if not shas:
        STATE.write_text(json.dumps({"last_sha": head}))
        return 0
    msgs = []
    for sha in shas:
        files = git("show", "--name-only", "--format=", sha, "--",
                    CARDS).split()
        for rel in files:
            name = Path(rel).stem
            if not rel.endswith(".yml"):
                continue
            new_txt = git("show", f"{sha}:{rel}")
            old_txt = git("show", f"{sha}^:{rel}")
            new = card_state(new_txt)
            old = card_state(old_txt) if old_txt else None
            msgs.append(summarize(name, old, new))
            if len(msgs) >= MAX_PER_TICK:
                break
        if len(msgs) >= MAX_PER_TICK:
            break
    if msgs:
        body = "\n".join(f"• {m}" for m in msgs)
        board_notify.send("[kanban]", body, url="")
    STATE.write_text(json.dumps({"last_sha": head, "ts": int(time.time())}))
    return 0


if __name__ == "__main__":
    sys.exit(main())