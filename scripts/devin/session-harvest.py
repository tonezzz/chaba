#!/usr/bin/env python3
"""session-harvest.py — inventory stale Devin sessions in sessions.db and
classify each for the dispatch-console loop.

Read-only. Per session: id, title, message count, real last activity
(max message_nodes.created_at — sessions.last_activity_at was reset by the
Sep-22 db rebuild), working dir, last user + assistant message snippets.

Verdicts:
  dispatched  — cwd under a dispatch-wt-* worktree; already in the loop
  trivial     — tiny session or auto-summary title; drop candidate
  done        — last message is a completed assistant reply
  awaiting    — last assistant message ends asking the user a question
  resume      — last message is USER (assistant was cut off / never replied)
                or unfinished research/wrap-up in a non-repo cwd
  redispatch  — unfinished work with pending code writes; giant sessions
                (>4000 msgs) also land here (context bloat kills resume)

Usage:
  session-harvest.py [--db PATH] [--json] [--min-msgs N] [--snippet N]
Typical: scp to host, run there, save stdout as reports/dispatch/harvest.md
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from datetime import datetime, timezone

DEFAULT_DB = "~/.local/share/devin/cli/sessions.db"
AUTO_TITLES = re.compile(
    r"^(output a summary|summary of the|the user asked|the session attempted|"
    r"the assistant (is|investigated|clarified)|compact\b|vacuum\b)",
    re.I)


def _ts(v) -> str:
    if not v:
        return ""
    try:
        v = float(v)
        if v > 1e12:
            v /= 1000.0
        return datetime.fromtimestamp(v, timezone.utc).strftime("%m-%d %H:%M")
    except Exception:
        return ""


def _msg_text(raw) -> tuple[str, str]:
    """Parse chat_message JSON -> (role, text)."""
    try:
        d = json.loads(raw)
        role = d.get("role", "")
        content = d.get("content", "")
        if isinstance(content, list):  # content blocks
            content = " ".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") in
                (None, "text", "output_text"))
        return role, " ".join(str(content).split())
    except Exception:
        return "", ""


def _tails(c: sqlite3.Connection, sid: str) -> tuple[int, str, str, str, str]:
    """msg count, last activity, last user text, last assistant text, last role."""
    msgs = c.execute(
        "select chat_message, created_at from message_nodes "
        "where session_id=? order by row_id", (sid,)).fetchall()
    last_user = last_asst = last_role = ""
    last_ts = ""
    for raw, ts in msgs:
        role, text = _msg_text(raw)
        if not role:
            continue
        last_role = role
        if ts and str(ts) > str(last_ts or ""):
            last_ts = ts
        if role == "user":
            last_user = text
        elif role == "assistant":
            last_asst = text
    return len(msgs), _ts(last_ts), last_user, last_asst, last_role


def classify(msgs: int, cwd: str, title: str, last_role: str,
             last_asst: str, last_user: str) -> tuple[str, str]:
    base = os.path.basename(cwd or "")
    if base.startswith("dispatch-wt-"):
        return "dispatched", "dispatch worktree — already in the loop"
    if msgs < 40 or AUTO_TITLES.match(title or ""):
        return "trivial", "tiny/auto-summary session"
    if msgs > 4000:
        return "redispatch", f"{msgs} msgs — resume would carry dead context"
    live_cwd = base in ("", "tony", "CascadeProjects", "home")
    if last_role == "user":
        why = "user message never answered"
        return ("redispatch" if not live_cwd or msgs > 400 else "resume"), why
    if last_asst.rstrip().endswith("?"):
        return "awaiting", "assistant ended on a question for you"
    if last_role == "assistant":
        if live_cwd:
            return "done", "assistant completed a reply in live checkout"
        return "done", "assistant completed a reply"
    return "trivial", "no user/assistant tail"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--min-msgs", type=int, default=0)
    ap.add_argument("--snippet", type=int, default=110)
    args = ap.parse_args()

    db = os.path.expanduser(args.db)
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    sessions = c.execute(
        "select id, title, working_directory, model from sessions").fetchall()

    rows = []
    for sid, title, cwd, model in sessions:
        msgs, last_ts, last_user, last_asst, last_role = _tails(c, sid)
        if msgs < args.min_msgs:
            continue
        verdict, why = classify(msgs, cwd or "", title or "",
                                last_role, last_asst, last_user)
        rows.append({
            "id": sid, "title": title or "?", "msgs": msgs,
            "last": last_ts, "cwd": cwd or "", "verdict": verdict,
            "why": why, "model": model or "",
            "last_user": last_user[: args.snippet],
            "last_asst": last_asst[: args.snippet],
        })

    order = {"awaiting": 0, "resume": 1, "redispatch": 2,
             "done": 3, "dispatched": 4, "trivial": 5}
    rows.sort(key=lambda r: (order.get(r["verdict"], 9), -r["msgs"]))

    if args.json:
        print(json.dumps(rows, indent=1, ensure_ascii=False))
        return 0

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    print(f"# Session harvest — {os.uname().nodename} "
          f"({datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z)\n")
    print("verdicts:", ", ".join(f"{k}={v}" for k, v in sorted(
        counts.items(), key=lambda kv: order.get(kv[0], 9))), "\n")
    cur = None
    for r in rows:
        if r["verdict"] != cur:
            cur = r["verdict"]
            print(f"\n## {cur}\n")
        print(f"- `{r['id'][:18]}` **{r['title'][:64]}** "
              f"({r['msgs']} msgs, {r['cwd'].rsplit('/', 1)[-1] or '~'})")
        print(f"  why: {r['why']}")
        if r["last_user"]:
            print(f"  user: {r['last_user']}")
        if r["last_asst"]:
            print(f"  asst: {r['last_asst']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
