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
review, writes a comms entry, and best-effort merges the session branch
into origin/<default_branch> in a throwaway detached worktree (skipped
when the worktree is dirty or the merge conflicts — the board-api close
gate still blocks those until merged by hand; KANBAN_AUTOMERGE=0
disables). Session-end notes report leftover dirty/unmerged state.
Tony reviews then presses Close.
"""
import fcntl
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dispatch_repos as dr

REPO = Path(__file__).resolve().parent.parent.parent
CARD_DIR = REPO / "docs/ssot/kanban/cards"
RENDER = REPO / "scripts/render-board.py"
LOCK = Path("/tmp/board-api.lock")
DISPATCH = os.environ.get("DEVIN_DISPATCH",
                          str(Path.home() / ".local/bin/devin-dispatch"))
# Unattended sessions die on permission rejection — 'smart' auto-rejects
# curl/systemctl and the rails ask agents to curl /comment. Worktree
# isolation + the no-push rails are the guardrail (same reasoning as
# dispatch-queue.sh's dangerous default).
os.environ.setdefault("DISPATCH_PERMISSION_MODE", "dangerous")
API = os.environ.get("BOARD_API", "http://127.0.0.1:8787")
HOST = os.uname().nodename
SESSION = f"kanban-dispatch@{HOST}"
# Per-host concurrency: count of active devin-task-* units we won't exceed.
# tony-dell is RAM-tight (dispatch-queue.sh used CAP=3); other hosts raise it
# via env until a per-host table lands in ssot.kanban.yml rules.
HOST_CAP = int(os.environ.get("KANBAN_HOST_CAP", "3"))


def active_tasks() -> int:
    r = sh(["systemctl", "--user", "list-units", "devin-task-*",
            "--state=active", "--no-legend"])
    return sum(1 for ln in r.stdout.splitlines() if ln.strip())

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
- If you need Tony to answer something, raise a board request — do NOT
  edit the card YAML directly (that races the API's flock):
    curl -s -X POST {api}/request \\
      -H 'Content-Type: application/json' \\
      -d '{{"id":"{id}","from":"devin","ask":"<question>"}}'
- If the card opts into the CI pipeline (a `pipeline: ci` field), run
  `python3 scripts/ci/card-pipeline.py {id} --api {api}` near the end —
  it audits your worktree diff and records benchmark before/after on the
  card (docs/ssot/ssot.ci.yml).
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
    a["runner"] = HOST
    card.setdefault("claim", {})["session"] = task_id
    card["claim"]["since"] = now()
    comms_add(card, "chaba", f"dispatched {task_id} on {repo}")
    return f"dispatched {task_id}"


def session_end_notes(card: dict) -> list:
    """Comms lines for leftover work at session end (merge-guard spec c):
    dirty worktree file count, plus commits not yet in the default branch
    (the same condition the board-api close gate blocks on)."""
    notes = []
    try:
        s = dr.session(card)
        if s["worktree"]:
            dirty = dr.dirty_count(s["worktree"])
            if dirty:
                notes.append(
                    f"session end: worktree {s['worktree'].name} dirty — "
                    f"{dirty} uncommitted file(s); commit or clean before "
                    f"pruning")
        if s["head"] and s["base_ref"]:
            m = dr.merge_state(s["repo_root"], s["head"], s["base_ref"])
            if m.get("checked") and not m["ancestor"]:
                notes.append(
                    f"session end: {m['unmerged']} commit(s) on "
                    f"{s['branch']} not in {s['base_ref']} — close will "
                    f"block until merged")
    except Exception:
        pass
    return notes


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
    if os.environ.get("KANBAN_AUTOMERGE", "1") != "0":
        try:
            res = dr.try_merge(card)
            if res.get("merged"):
                comms_add(card, "chaba",
                          res.get("note") or "session branch merged")
            else:
                why = res.get("error") or res.get("skipped") or "unknown"
                comms_add(card, "chaba",
                          f"auto-merge not done: {why} — close will block "
                          f"until merged")
        except Exception as e:
            comms_add(card, "chaba",
                      f"auto-merge error: {e} — merge manually")
    for n in session_end_notes(card):
        comms_add(card, "chaba", n)
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
                pinned = a.get("host")
                if pinned and pinned != HOST:
                    continue  # pinned to another host's dispatcher
                if a.get("runner") and a["runner"] != HOST:
                    continue  # already claimed by another host
                if active_tasks() >= HOST_CAP:
                    print(f"{card['id']}: skipped — host cap {HOST_CAP}")
                    continue
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
