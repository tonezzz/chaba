#!/usr/bin/env python3
"""Focus-inbox write door — served checkout or board-api, never litter.

docs/ssot/focus-inbox is swept into git ONLY by kanban-commit.timer on the
served checkout (default ~/CascadeProjects/chaba-tony-dell on idc03).
Checkouts marked chaba-role exec|readonly cannot commit (the pre-commit
checkout-role guard blocks them), so inbox files written there are
invisible litter — the 2026-11-14 tony-omen incident (875 files).

Contract for writers:

- local_writes_ok(repo_root) -> bool
    True when files under repo_root can actually reach master — mirrors
    the pre-commit role guard exactly: exec/readonly block, everything
    else (served, job, branch, experiment, unmarked) is allowed.
- post_inbox(payload) -> bool
    POST a focus-inbox item to board-api /inbox — the served checkout on
    idc03 writes + commits it. payload keys mirror board-api do_inbox:
    text (required), label, priority, tags, missing_info, subtasks,
    owner, session, icon, subtitle, safe_to_parallel.

Alert producers on non-committable checkouts should post_inbox() per
alert; renderers and stateful/deduping tools should skip file writes
entirely (their canonical instance runs on the served checkout).
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from pathlib import Path

BLOCKING_ROLES = frozenset({"exec", "readonly"})
DEFAULT_SERVED = os.path.expanduser("~/CascadeProjects/chaba-tony-dell")
DEFAULT_BOARD_API = "https://idc03.taila0626a.ts.net:10000"


def _git(root: Path, *args: str) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def checkout_role(root: Path | str) -> str:
    """chaba-role marker for the checkout containing `root` ("" = unmarked
    git worktree; "__nogit__" = not a git worktree at all)."""
    gitdir = _git(Path(root), "rev-parse", "--absolute-git-dir")
    if not gitdir:
        return "__nogit__"
    try:
        return (Path(gitdir) / "chaba-role").read_text().strip()
    except OSError:
        return ""


def local_writes_ok(root: Path | str) -> bool:
    """True when focus-inbox files written under `root` can be committed —
    i.e. `root` is inside a git worktree not marked exec/readonly. A plain
    directory (e.g. the non-git chaba-tony-dell replica on tony-omen) can
    never reach master, so it returns False."""
    role = checkout_role(root)
    return role not in BLOCKING_ROLES and role != "__nogit__"


def board_api() -> str:
    return (os.environ.get("BOARD_API")
            or os.environ.get("RUNNER_API")
            or DEFAULT_BOARD_API).rstrip("/")


def post_inbox(payload: dict, timeout: int = 20,
               api: str | None = None) -> bool:
    """POST one focus-inbox item to board-api /inbox. Returns True on 2xx.
    Never raises — callers decide the fallback (skip + warn)."""
    text = str(payload.get("text") or "").strip()
    if not text:
        return False
    label = str(payload.get("label") or payload.get("title") or "").strip() \
        or " ".join(text.split())[:80]
    body = {
        "text": text[:4000],
        "label": label[:120],
        "priority": str(payload.get("priority") or "medium")[:20],
        "tags": [str(t)[:40] for t in (payload.get("tags") or [])][:20],
        "owner": str(payload.get("owner") or "tony")[:40],
        "session": str(payload.get("session") or "")[:80],
    }
    for k in ("subtitle", "icon", "missing_info", "subtasks",
              "safe_to_parallel", "parallel_reason"):
        if payload.get(k) is not None:
            body[k] = payload[k]
    try:
        req = urllib.request.Request(
            (api or board_api()) + "/inbox",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception:
        return False
