#!/usr/bin/env python3
"""Ada memory health checks that emit chaba-events.

Checks (hourly via ada-memory-health.timer on tony-omen):
  1. NotebookLM REST auth — GET http://tony-dell:3011/health/auth; failure means
     the deep-recall tier is silently dead until a human re-authenticates.
  2. Inbox age — docs/ada-memory/inbox/**/*.md files older than 7 days are
     unreviewed voice notes waiting on human promotion.

Dedup: a state file remembers when each condition was last emitted; a firing
condition re-emits only when it newly appears or every 24h while persisting.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INBOX = REPO / "docs/ada-memory/inbox"
STATE = Path.home() / ".cache/ada-memory-health.json"
NLM_HEALTH = "http://tony-dell:3011/health/auth"
INBOX_MAX_AGE_S = 7 * 24 * 3600
REEMIT_AFTER_S = 24 * 3600

EVENT_CMD = [
    "ssh", "tony-dell",
    "python3", "/home/tony/.config/home-assistant/scripts/chaba-event-log.py",
    "add", "-",
]


def emit(check: str, title: str, body: str, requires_response: bool) -> None:
    payload = json.dumps({
        "title": title,
        "category": "ada-memory",
        "source": "memory-health-check",
        "severity": "warn",
        "body": body,
        "requires_response": requires_response,
        "confidence": 0.9,
    })
    try:
        r = subprocess.run(EVENT_CMD, input=payload, capture_output=True,
                           text=True, timeout=30)
        print(f"emit {check}: {'ok' if r.returncode == 0 else r.stderr.strip()}")
    except Exception as exc:
        print(f"emit {check} failed: {exc}")


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def maybe_emit(state: dict, check: str, firing: bool, title: str,
               body: str, requires_response: bool) -> None:
    now = time.time()
    last = state.get(check, {}).get("last_emit", 0)
    was_firing = state.get(check, {}).get("firing", False)
    if firing and (not was_firing or now - last > REEMIT_AFTER_S):
        emit(check, title, body, requires_response)
        state[check] = {"firing": True, "last_emit": now}
    else:
        state.setdefault(check, {})["firing"] = firing
        state[check].setdefault("last_emit", last)


def check_nlm_auth() -> tuple[bool, str]:
    try:
        req = urllib.request.Request(NLM_HEALTH,
                                     headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
            ok = resp.status == 200 and bool(
                data.get("ok") or data.get("authenticated"))
            return ok, f"HTTP {resp.status} {data}"
    except Exception as exc:
        return False, str(exc)


def check_inbox_age() -> tuple[bool, str]:
    if not INBOX.is_dir():
        return False, "no inbox"
    now = time.time()
    old = [p for p in INBOX.rglob("*.md")
           if p.is_file() and now - p.stat().st_mtime > INBOX_MAX_AGE_S]
    if not old:
        return False, "inbox fresh"
    names = ", ".join(p.name for p in old[:5])
    more = f" +{len(old) - 5} more" if len(old) > 5 else ""
    return True, f"{len(old)} note(s) >7d: {names}{more}"


def main() -> int:
    state = load_state()

    ok, detail = check_nlm_auth()
    maybe_emit(
        state, "nlm-auth", not ok,
        "NotebookLM auth broken — deep recall degraded",
        f"/health/auth on tony-dell:3011 reports: {detail}. "
        "Voice recall still works via MDDB banks, but NotebookLM escalation "
        "fails until a human re-authenticates (nlm login / cookie bridge).",
        requires_response=True,
    )

    firing, detail = check_inbox_age()
    maybe_emit(
        state, "inbox-age", firing,
        "Ada memory inbox has unreviewed voice notes",
        f"{detail}. Review docs/ada-memory/inbox/ — promote with "
        "consolidate-memory.py or discard.",
        requires_response=True,
    )

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
