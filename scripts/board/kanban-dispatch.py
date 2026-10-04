#!/usr/bin/env python3
"""kanban-dispatch — drain cards whose action.status is 'queued'.

Runs from kanban-dispatch.timer every 2 min on tony-dell, in the
chaba-tony-dell checkout (the web-served tree). For each queued card:

  1. builds the task text (card.spec, else title+note) with standard
     rails (worktree already handled by devin-dispatch; report back via
     the board API so the card's comms log stays live)
  2. devin-dispatch start <repo> "<task>"  -> action.task_id
  3. claims the card for this dispatch session, status -> running

For cards already 'running', polls `devin-dispatch status <task_id>`;
when the unit finishes, marks action.status done, moves the card to
review, and writes a comms entry. Tony reviews then presses Close.
"""
import fcntl
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent.parent
CARD_DIR = REPO / "docs/ssot/kanban/cards"
RENDER = REPO / "scripts/render-board.py"
LOCK = Path("/tmp/board-api.lock")
DISPATCH = os.environ.get("DEVIN_DISPATCH",
                          str(Path.home() / ".local/bin/devin-dispatch"))
API = os.environ.get("BOARD_API", "http://127.0.0.1:8787")
SESSION = f"kanban-dispatch@{os.uname().nodename}"

TASK_RAILS = """
---
Rails: you are processing kanban card '{id}' (docs/ssot/kanban/cards/{id}.yml).
- Work in the worktree devin-dispatch gave you; do NOT push unless the
  card spec explicitly says to.
- While you work, post progress to the card so the board stays live:
    curl -s -X POST {api}/comment \\
      -H 'Content-Type: application/json' \\
      -d '{{"id":"{id}","from":"devin","text":"<short status>"}}'
- When done, post a final comms entry summarizing outcome + where the
  deliverables are. The dispatcher will mark the action done and move
  the card to review.
- If you need Tony to answer something, edit the card file and add a
  requests: entry (id, ask, status: open) instead of blocking.
""".strip()


def now() -> str:
    return datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M")


def comms_add(card: dict, frm: str, text: str) -> None:
    card.setdefault("comms", []).append(
        {"at": now(), "from": frm, "text": text[:500]}
    )


def sh(cmd: list, timeout=60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def unit_state(task_id: str) -> str:
    """devin-dispatch tasks run as devin-task-<id>.service user units."""
    r = sh(["systemctl", "--user", "is-active", f"devin-task-{task_id}.service"])
    return r.stdout.strip() or "unknown"


def queue_one(path: Path, card: dict) -> str:
    a = card["action"]
    repo = a.get("repo", "chaba")
    spec = (card.get("spec") or "").strip() or f"{card.get('title','')}\n\n{card.get('note','')}"
    task = spec + "\n\n" + TASK_RAILS.format(id=card["id"], api=API)

    r = sh([DISPATCH, "start", repo, task], timeout=120)
    if r.returncode != 0:
        a["status"] = "failed"
        a["result"] = f"dispatch failed: {(r.stderr or r.stdout).strip()[:300]}"
        comms_add(card, "chaba", f"dispatch failed: {a['result'][:120]}")
        return "dispatch failed"

    task_id = r.stdout.strip().splitlines()[-1].strip()
    a["status"] = "running"
    a["task_id"] = task_id
    card.setdefault("claim", {})["session"] = task_id
    card["claim"]["since"] = now()
    comms_add(card, "chaba", f"dispatched {task_id} on {repo}")
    return f"dispatched {task_id}"


def poll_one(path: Path, card: dict) -> str:
    a = card["action"]
    tid = a.get("task_id") or ""
    state = unit_state(tid) if tid else "unknown"
    if state in ("active", "activating"):
        return "still running"
    # unit left the active state — treat as finished
    a["status"] = "done"
    a["result"] = f"{tid} finished ({state}) — see `devin-dispatch logs {tid}`"
    card["column"] = "review"
    card.setdefault("claim", {}).pop("session", None)
    comms_add(card, "chaba", f"run finished ({state}) → review")
    return "finished"


def main() -> int:
    changed = False
    with LOCK.open("w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        for p in sorted(CARD_DIR.glob("*.yml")):
            card = yaml.safe_load(p.read_text()) or {}
            a = card.get("action") or {}
            st = a.get("status")
            if st == "queued":
                card.setdefault("id", p.stem)
                msg = queue_one(p, card)
            elif st == "running":
                card.setdefault("id", p.stem)
                msg = poll_one(p, card)
            else:
                continue
            card["updated"] = now()
            p.write_text(
                yaml.safe_dump(card, allow_unicode=True, sort_keys=False, width=110))
            print(f"{card['id']}: {msg}")
            changed = True
    if changed:
        subprocess.run([sys.executable, str(RENDER)], cwd=REPO, check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
