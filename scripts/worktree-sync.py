#!/usr/bin/env python3
"""Check worktree branches for drift and draft focus-inbox items."""

import json
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INBOX_DIR = REPO / "docs" / "ssot" / "focus-inbox"


def run(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, text=True, cwd=REPO).strip()
    except subprocess.CalledProcessError:
        return ""


def slugify(text):
    return re.sub(r"[^a-z0-9_-]", "", text.lower().replace(" ", "-"))[:40]


def make_inbox_path(prefix):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    return INBOX_DIR / f"{ts}-{prefix}.yml"


def write_draft(branch, ahead, behind):
    INBOX_DIR.mkdir(exist_ok=True)
    path = make_inbox_path(f"worktree-drift-{slugify(branch)}")
    body = f"""title: Focus Inbox Item
subtitle: Worktree drift detected
icon: inbox

focus:
  label: Sync worktree {branch} with master
  text: |
    Worktree {branch} is {ahead} commit(s) ahead and {behind} commit(s) behind master.
    Decide whether to merge, rebase, or archive the branch.
  branch: chaba
  priority: medium
  status: draft
  triage_score: 0.55
  tags: ["worktree", "sync", "branches"]
  safe_to_parallel:
    value: true
    reason: Worktree sync is independent per branch.
  subtasks:
    - label: Review {branch} changes
    - label: Merge or rebase to master
    - label: Delete worktree if merged

ownership:
  owner: tony
  session: ""
  locked: false
  lock_reason: ""

source:
  session: ""
  date: '{datetime.now(timezone.utc).strftime("%Y-%m-%d")}'
"""
    path.write_text(body, encoding="utf-8")
    print(f"Drafted: {path}")


def main():
    out = run("git worktree list --porcelain")
    if not out:
        return
    for block in out.split("\n\n"):
        worktree = None
        branch = None
        for line in block.splitlines():
            if line.startswith("worktree "):
                worktree = line[9:]
            if line.startswith("branch "):
                branch = line[7:]
        if not branch or branch == "refs/heads/master" or branch == "master":
            continue
        short = branch.replace("refs/heads/", "")
        ahead = run(f"git rev-list --count master..{shlex.quote(short)}") or "0"
        behind = run(f"git rev-list --count {shlex.quote(short)}..master") or "0"
        if int(ahead) > 0 or int(behind) > 0:
            write_draft(short, int(ahead), int(behind))


if __name__ == "__main__":
    main()
