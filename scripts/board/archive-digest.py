#!/usr/bin/env python3
"""archive-digest — weekly Education extraction for archived kanban cards
(KNB-1178 follow-up).

Scans docs/ssot/kanban/cards/archive/*.yml for cards archived in the last
DIGEST_DAYS (default 7 — `updated` is stamped at archive time), groups
them by ref prefix, and upserts a rolling lesson "kanban-shipped-digest"
through scripts/lesson-add.py (board-api /lesson door -> WP lesson CPT +
MDDB chaba-lessons mirror). Runs on idc03 where board-api is localhost.

Usage: archive-digest.py [--days N] [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CARD_ARCHIVE = Path(os.environ.get(
    "KANBAN_ARCHIVE_DIR", REPO / "docs/ssot/kanban/cards/archive"))
LESSON_ADD = REPO / "scripts" / "lesson-add.py"
TZ = dt.timezone(dt.timedelta(hours=7))
TOPIC = "kanban-shipped-digest"


def archived_since(days: float) -> list[dict]:
    cutoff = dt.datetime.now() - dt.timedelta(days=days)
    out = []
    if not CARD_ARCHIVE.is_dir():
        return out
    for p in sorted(CARD_ARCHIVE.glob("*.yml")):
        try:
            c = yaml.safe_load(p.read_text()) or {}
        except Exception:
            continue
        if not isinstance(c, dict):
            continue
        upd = str(c.get("updated") or "")
        try:
            when = dt.datetime.strptime(upd, "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        if when >= cutoff:
            out.append({"id": c.get("id") or p.stem,
                        "ref": str(c.get("ref") or ""),
                        "title": str(c.get("title") or ""),
                        "updated": upd,
                        "brief": str(c.get("brief") or "")[:160]})
    return out


def render_html(cards: list[dict], days: float) -> str:
    groups = defaultdict(list)
    for c in cards:
        prefix = c["ref"].split("-")[0] if c["ref"] else "other"
        groups[prefix].append(c)
    parts = [f"<h2>Kanban shipped digest — last {days:g}d</h2>",
             f"<p>{len(cards)} verified done cards archived. "
             "Source: docs/ssot/kanban/cards/archive/</p>"]
    for prefix in sorted(groups):
        parts.append(f"<h3>{html.escape(prefix)} ({len(groups[prefix])})</h3><ul>")
        for c in sorted(groups[prefix],
                        key=lambda x: x["updated"], reverse=True):
            ref = f"{html.escape(c['ref'])} " if c["ref"] else ""
            brief = (f" — {html.escape(c['brief'])}"
                     if c["brief"] else "")
            parts.append(
                f"<li>{ref}<b>{html.escape(c['title'])}</b> "
                f"<i>({html.escape(c['updated'])})</i>{brief}</li>")
        parts.append("</ul>")
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=float, default=7.0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cards = archived_since(args.days)
    print(f"{len(cards)} cards archived in last {args.days}d")
    if not cards:
        return 0
    body = render_html(cards, args.days)
    if args.dry_run:
        print(body[:2000])
        return 0

    tmp = Path("/tmp/kanban-shipped-digest.html")
    tmp.write_text(body)
    r = subprocess.run(
        [sys.executable, str(LESSON_ADD), "--topic", TOPIC,
         "--level", "working", "--source", "chat", "--no-th",
         "--content-file", str(tmp)],
        capture_output=True, text=True, timeout=180)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode:
        print("digest: lesson-add failed", file=sys.stderr)
        return r.returncode
    print(f"digest upserted -> lesson '{TOPIC}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
