#!/usr/bin/env python3
"""inbox_door — the non-writer focus-inbox door (card
exec-checkout-generated-writes-focus-inb-da698a).

Focus-inbox entries are repo files under docs/ssot/focus-inbox/ that only
the served (writer) checkout's kanban-commit ever commits. Producers
running on exec/readonly/job checkouts must NOT write them locally —
the files die as permanent working-tree drift (omen accumulated
hundreds). This module gives every producer one decision:

  - ``local_writable(repo)`` — True only when the checkout can actually
    land the file (served role, or an unstamped legacy checkout that can
    still commit — the pre-commit block is role-based).
  - ``emit(...)`` — post a focus-inbox entry through board-api
    ``POST /inbox`` (the unified write door, docs/kb/board-api-write-door.md).
    ``BOARD_API`` env overrides the default endpoint.

Use pattern::

    from inbox_door import local_writable, emit
    if local_writable(REPO):
        ... existing file write ...
    else:
        emit(text=..., label=..., tags=[...], session="my-producer")

For producers whose inbox entries are structured YAML with lifecycle
(GC/heal/update semantics the /inbox door can't express), prefer
``local_writable`` alone and skip the emit — running the producer on the
served checkout is the correct fix there (report-watch pattern).
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from pathlib import Path

from checkout_role import checkout_role

BOARD_API = os.environ.get(
    "BOARD_API", "https://idc03.taila0626a.ts.net:10000").rstrip("/")


def local_writable(repo) -> bool:
    """True when focus-inbox file writes in ``repo`` can reach origin.

    Stamped non-writer roles (exec/readonly/job/branch/experiment) ->
    False. Unstamped checkouts -> True (legacy: no role block, commits
    still work — same semantics as merge-sweep's checkout_role check).
    """
    role = checkout_role(repo)
    return not role or role == "served"


def post_inbox(*, text: str, label: str = "", priority: str = "medium",
               tags=None, owner: str = "tony", session: str = "",
               missing_info=None, subtasks=None,
               safe_to_parallel=None, timeout: int = 20) -> bool:
    """POST one entry to board-api /inbox. Returns True on 2xx.

    Raises nothing — callers log the False return; an unreachable door
    must never crash the producer (same contract as the file path's
    best-effort writes).
    """
    text = (text or "").strip()
    if not text:
        return False
    body = {
        "text": text[:4000],
        "label": (label or " ".join(text.split())[:80])[:120],
        "priority": priority,
        "tags": [str(t)[:40] for t in (tags or [])][:20],
        "owner": owner,
        "session": session[:80],
    }
    if missing_info:
        body["missing_info"] = [str(m)[:200] for m in missing_info][:10]
    if subtasks:
        body["subtasks"] = [
            {"label": str(s.get("label") if isinstance(s, dict) else s)[:200],
             "status": str(s.get("status") if isinstance(s, dict)
                           else "not_started")[:20]}
            for s in subtasks][:20]
    if safe_to_parallel is not None:
        body["safe_to_parallel"] = safe_to_parallel
    try:
        req = urllib.request.Request(
            f"{BOARD_API}/inbox", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def emit(repo, *, text: str, label: str = "", priority: str = "medium",
         tags=None, session: str = "", **kw) -> str:
    """Route one inbox entry: local file write is the caller's job — this
    helper only handles the API side. Returns 'api' on successful post,
    'api-failed' otherwise. Callers fall back to their file write or log.
    """
    ok = post_inbox(text=text, label=label, priority=priority, tags=tags,
                    session=session, **kw)
    return "api" if ok else "api-failed"


_DEDUPE_FILE = Path.home() / ".local" / "state" / "inbox-door-posted.json"


def _dedupe_seen(key: str) -> bool:
    try:
        return key in json.loads(_DEDUPE_FILE.read_text())
    except Exception:
        return False


def _dedupe_mark(key: str) -> None:
    try:
        _DEDUPE_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            seen = json.loads(_DEDUPE_FILE.read_text())
        except Exception:
            seen = {}
        seen[key] = True
        _DEDUPE_FILE.write_text(json.dumps(seen))
    except Exception:
        pass


def emit_doc(doc: dict, *, session: str = "", dedupe: bool = True) -> str:
    """Route a whole focus-inbox YAML doc (title/focus/ownership/source
    shape) through the door. Returns 'api' | 'api-failed' | 'dup'.

    ``dedupe`` keys on sha256(session|label|text) in a local state file —
    the remote inbox has no open_item view, so producers that used to
    glob local files for duplicates need this instead.
    """
    focus = (doc or {}).get("focus") or {}
    text = str(focus.get("text") or "").strip()
    if not text:
        return "api-failed"
    label = str(focus.get("label") or doc.get("title") or "")
    key = hashlib.sha256(
        f"{session}|{label}|{text}".encode()).hexdigest()
    if dedupe and _dedupe_seen(key):
        return "dup"
    ok = post_inbox(
        text=text, label=label,
        priority=str(focus.get("priority") or "medium"),
        tags=focus.get("tags") or [],
        owner=str((doc.get("ownership") or {}).get("owner") or "tony"),
        session=session or str((doc.get("source") or {}).get("session") or ""),
        missing_info=focus.get("missing_info"),
        subtasks=focus.get("subtasks"),
        safe_to_parallel=(focus.get("safe_to_parallel") or {}).get("value")
        if isinstance(focus.get("safe_to_parallel"), dict) else None)
    if ok and dedupe:
        _dedupe_mark(key)
    return "api" if ok else "api-failed"
