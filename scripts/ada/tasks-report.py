#!/usr/bin/env python3
"""Tasks digest (L1.5j): Google Tasks created-vs-done via the Ada token.

Self-contained read-only pass — same token file the Ada calendar service
uses (~/.config/secrets/ada-google-calendar-token.json), refresh-token
flow inline so this repo doesn't depend on ada-pi internals. Personal-tier
data — local only.

Usage:
  tasks-report.py [--days 7]
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from pathlib import Path

import httpx

TOKEN_FILE = Path("~/.config/secrets/ada-google-calendar-token.json"
                  ).expanduser()
TOKEN_URI = "https://oauth2.googleapis.com/token"
TASKS_API = "https://tasks.googleapis.com/tasks/v1"
DEFAULT_OUT = Path.home() / ".local/share/ada-review"


def _access_token() -> str | None:
    try:
        creds = json.loads(TOKEN_FILE.read_text())
        r = httpx.post(creds.get("token_uri") or TOKEN_URI, data={
            "grant_type": "refresh_token",
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
            "refresh_token": creds["refresh_token"],
        }, timeout=15)
        if r.status_code != 200:
            print(f"warn: token refresh HTTP {r.status_code}",
                  file=sys.stderr)
            return None
        return r.json()["access_token"]
    except Exception as e:
        print(f"warn: auth: {e}", file=sys.stderr)
        return None


def _get(token: str, url: str, **params) -> dict:
    r = httpx.get(url, headers={"Authorization": f"Bearer {token}"},
                  params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def _parse_ts(s: str | None) -> datetime.datetime | None:
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def tasks_block(rows: list[dict], since: str) -> str:
    lines = [f"## tasks ({since})"]
    if not rows:
        lines.append("no task data")
        return "\n".join(lines)
    for r in rows:
        flag = " ⚠" if r["overdue"] else ""
        lines.append(
            f"{r['list']}: {r['open']} open, {r['done_recent']} done, "
            f"{r['created_recent']} new, {r['overdue']} overdue{flag}")
        for t in r["open_titles"][:5]:
            lines.append(f"  - {t}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    token = _access_token()
    if not token:
        return 1
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=args.days)

    rows = []
    try:
        lists = _get(token, f"{TASKS_API}/users/@me/lists").get("items", [])
    except Exception as e:
        print(f"warn: tasklists: {e}", file=sys.stderr)
        return 1

    for lst in lists:
        lid, title = lst["id"], lst.get("title", lst["id"])
        try:
            items = _get(token, f"{TASKS_API}/lists/{lid}/tasks",
                         showCompleted="true", showHidden="true",
                         maxResults=200).get("items", [])
        except Exception as e:
            print(f"warn: {title}: {e}", file=sys.stderr)
            continue
        open_t, done_recent, created_recent, overdue = [], 0, 0, 0
        for t in items:
            status = t.get("status")
            completed = _parse_ts(t.get("completed"))
            updated = _parse_ts(t.get("updated"))
            due = _parse_ts(t.get("due"))
            if status == "completed":
                if completed and completed >= cutoff:
                    done_recent += 1
            else:
                title_t = t.get("title") or "(untitled)"
                open_t.append(title_t)
                if due and due < now:
                    overdue += 1
                if updated and updated >= cutoff:
                    created_recent += 1
        rows.append({"list": title, "open": len(open_t),
                     "done_recent": done_recent,
                     "created_recent": created_recent,
                     "overdue": overdue, "open_titles": open_t[:8]})

    args.out.mkdir(parents=True, exist_ok=True)
    ops = args.out / "tasks-ops.jsonl"
    with ops.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows)} lists -> {ops}")
    print(tasks_block(rows, f"{args.days}d"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
