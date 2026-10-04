#!/usr/bin/env python3
"""kanban-cms — render docs/ssot/kanban/cards/*.yml into the dev-kanban
CMS page. Replaces the hand-maintained page: the board is always live.

Sections: Automation health (cms-auto-* cards first — they are failures
asking for work), then Review, Backlog, Done grouped by column. Runs on
any host with a chaba checkout + MDDB access; a --check mode prints the
markdown without publishing.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import yaml

MDDB = os.environ.get("MDDB_BASE_URL", "http://100.74.146.0:11023/v1").rstrip("/")
COLLECTION = "ada-cms-pages"
REPO = Path(os.environ.get(
    "CHABA_REPO",
    str(Path(__file__).resolve().parents[2])))
CARDS = REPO / "docs" / "ssot" / "kanban" / "cards"
HASH_FILE = Path(os.environ.get(
    "KANBAN_CMS_HASH", "/tmp/kanban-cms-pub-hash.json"))
COLUMN_ORDER = ["review", "in-progress", "active", "backlog", "done"]
COLUMN_TITLE = {
    "review": "Needs attention",
    "in-progress": "In progress",
    "active": "Active",
    "backlog": "Backlog",
    "done": "Done",
}


def _truncate(s: str, n: int = 110) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def load_cards() -> list[dict]:
    cards = []
    for p in sorted(CARDS.glob("*.yml")):
        try:
            c = yaml.safe_load(p.read_text()) or {}
        except Exception:
            continue
        c["_file"] = p.stem
        c.setdefault("id", p.stem)
        cards.append(c)
    return cards


def row(c: dict) -> str:
    prio = f" · {c['priority']}" if c.get("priority") else ""
    upd = f" · {c['updated']}" if c.get("updated") else ""
    note = _truncate(c.get("note") or "")
    return f"| {c.get('title') or c['id']} | {note} |{prio}{upd} |"


def render(cards: list[dict]) -> str:
    auto = [c for c in cards if str(c.get("id", "")).startswith("cms-auto-")]
    prog_cards = [c for c in cards if c.get("program")]
    rest = [c for c in cards
            if not str(c.get("id", "")).startswith("cms-auto-")
            and not c.get("program")]
    out = ["# Dev Kanban",
           "",
           ("Live board rendered from `docs/ssot/kanban/cards/*.yml` "
            f"({len(cards)} cards). Health cards auto-open when a CMS "
            "automation goes stale and auto-close when it recovers."),
           ""]
    if auto:
        open_auto = [c for c in auto if c.get("column") != "done"]
        out += ["## Automation health", "",
                "| page | state | |",
                "|---|---|---|"]
        out += [row(c) for c in open_auto] or ["| — | all healthy | |"]
        out.append("")
    # Programs: cards with `program:` group under their <name>-program epic
    progs: dict[str, list[dict]] = {}
    for c in prog_cards:
        progs.setdefault(c["program"], []).append(c)
    for prog, members in sorted(progs.items()):
        epic = next((c for c in members
                     if c.get("id") == f"{prog}-program"), None)
        kids = [c for c in members if c is not epic]
        out += [f"## Program: {(epic or {}).get('title') or prog}", ""]
        if epic:
            m = _truncate(epic.get("metric") or "", 160)
            if m:
                out += [f"**Target:** {m}", ""]
        out += ["| card | state | metric / note |", "|---|---|---|"]
        kids.sort(key=lambda c: COLUMN_ORDER.index(c["column"])
                  if c.get("column") in COLUMN_ORDER else len(COLUMN_ORDER))
        for c in kids:
            out.append(f"| {c.get('title') or c['id']} | "
                       f"{c.get('column') or '?'} | "
                       f"{_truncate(c.get('metric') or c.get('note') or '')} |")
        out.append("")
    by_col: dict[str, list[dict]] = {}
    for c in rest:
        by_col.setdefault(str(c.get("column") or "backlog"), []).append(c)
    for col in COLUMN_ORDER + sorted(set(by_col) - set(COLUMN_ORDER)):
        items = by_col.get(col)
        if not items:
            continue
        if col == "done":
            items = sorted(items, key=lambda c: str(c.get("updated") or ""),
                           reverse=True)[:15]
        out += [f"## {COLUMN_TITLE.get(col, col.title())} ({len(items)})",
                "", "| card | note | |", "|---|---|---|"]
        out += [row(c) for c in items]
        out.append("")
    return "\n".join(out)


def publish(md: str, title: str, lang: str = "en") -> bool:
    try:
        pub = json.loads(HASH_FILE.read_text())
    except Exception:
        pub = {}
    h = hashlib.sha256(md.encode()).hexdigest()[:16]
    hkey = f"dev-kanban:{lang}"
    if pub.get(hkey) == h:
        return True
    meta = {
        "kind": ["page"], "attribute": ["page"], "bank": ["cms"],
        "slug": ["dev-kanban"], "subject": ["dev-kanban"],
        "title": [title], "format": ["markdown"], "lang": [lang],
        "domain": ["dev"], "scope": ["tony"], "status": ["active"],
        "source": ["api"], "generated_by": ["kanban-cms"],
        "sources": ["kanban-cards"], "fresh_for": ["3600"],
        "updated": [time.strftime("%Y-%m-%dT%H:%M:%S+00:00",
                                  time.gmtime())],
        "instance": ["kanban-cms"],
    }
    body = json.dumps({"collection": COLLECTION, "key": "dev-kanban",
                       "lang": lang, "contentMd": md,
                       "meta": meta}).encode()
    req = urllib.request.Request(f"{MDDB}/add", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.status < 300:
                pub[hkey] = h
                try:
                    HASH_FILE.write_text(json.dumps(pub))
                except Exception:
                    pass
                return True
    except Exception as exc:
        print(f"mddb add dev-kanban/{lang}: {exc}", file=sys.stderr)
    return False


def main() -> int:
    check = "--check" in sys.argv
    cards = load_cards()
    md = render(cards)
    md += ("\n\n---\n*Generated by kanban-cms from "
           "docs/ssot/kanban/cards/*.yml.*\n")
    if check:
        print(md)
        return 0
    ok = publish(md, "Dev Kanban", "en")
    th = md.replace("# Dev Kanban", "# กระดานงาน Dev", 1)
    ok &= publish(th, "กระดานงาน Dev", "th")
    print(f"kanban-cms: {len(cards)} cards, publish={'ok' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
