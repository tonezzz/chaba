#!/usr/bin/env python3
"""Render the kanban board: ssot.kanban.yml + cards/*.yml -> static HTML.

Pilot version — document-first like the rest of the stack: edit a card
file, re-run this script, commit.
"""
import html
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "docs/ssot/kanban/ssot.kanban.yml"


def main():
    man = yaml.safe_load(MANIFEST.read_text())
    card_dir = REPO / man["card_dir"]
    out_path = REPO / man["board_output"]

    cards = []
    for p in sorted(card_dir.glob("*.yml")):
        c = yaml.safe_load(p.read_text())
        c.setdefault("id", p.stem)
        cards.append(c)

    cols = man["columns"]
    limit = man.get("rules", {}).get("doing_limit", 2)
    counts = {c["id"]: 0 for c in cols}
    for c in cards:
        counts[c.get("column", "backlog")] = counts.get(c.get("column", "backlog"), 0) + 1

    doing_sessions = {}
    for c in cards:
        if c.get("column") == "doing" and c.get("claim", {}).get("session"):
            doing_sessions[c["claim"]["session"]] = doing_sessions.get(c["claim"]["session"], 0) + 1
    over = [s for s, n in doing_sessions.items() if n > limit]

    warn = ""
    if over:
        warn = (
            '<div class="bg-amber-900/50 border border-amber-600 rounded p-3 mb-4 text-amber-200 text-sm">'
            f'WIP limit exceeded (doing &gt; {limit}/session): {html.escape(", ".join(over))}</div>'
        )

    col_html = ""
    for col in cols:
        body = ""
        for c in cards:
            if c.get("column") != col["id"]:
                continue
            claim = c.get("claim") or {}
            badges = ""
            if claim.get("session"):
                badges += f'<span class="text-xs bg-sky-800 text-sky-200 rounded px-1.5 py-0.5">⚙ {html.escape(str(claim["session"]))}</span> '
            if c.get("blocked_by"):
                badges += f'<span class="text-xs bg-red-900/60 text-red-200 rounded px-1.5 py-0.5">blocked: {html.escape(str(c["blocked_by"]))}</span>'
            note = html.escape(str(c.get("note", "")))
            body += (
                '<div class="bg-slate-800 border border-slate-700 rounded-lg p-3 mb-2">'
                f'<div class="font-medium text-sm">{html.escape(str(c.get("title", c["id"])))}</div>'
                f'<div class="mt-1.5 flex flex-wrap gap-1">{badges}</div>'
                f'<div class="text-xs text-slate-400 mt-1.5">{note}</div>'
                f'<div class="text-[10px] text-slate-500 mt-1">{html.escape(c["id"])} · {html.escape(str(c.get("updated", "")))}</div>'
                "</div>"
            )
        if not body:
            body = '<div class="text-slate-500 text-sm italic">—</div>'
        col_html += (
            '<div class="flex-1 min-w-[220px]">'
            f'<div class="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">'
            f'{html.escape(col["title"])} · {counts.get(col["id"], 0)}</div>'
            f'<div class="bg-slate-800/40 border border-slate-700/60 rounded-lg p-2 min-h-[80px]">{body}</div>'
            "</div>"
        )

    ts = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M %Z")
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#0f172a">
  <title>Board</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-900 text-slate-100 min-h-screen">
  <nav class="bg-slate-800 border-b border-slate-700 px-4 py-3 flex items-center gap-3">
    <a href="/apps/" class="text-sky-400 hover:text-sky-300">← Apps</a>
    <span class="text-slate-500">|</span>
    <span class="font-semibold">Board</span>
    <span class="text-slate-500 text-xs ml-auto">rendered {html.escape(ts)}</span>
  </nav>
  <main class="p-4">
    {warn}
    <div class="flex gap-3 overflow-x-auto pb-4">{col_html}</div>
    <p class="text-xs text-slate-500 mt-2">Pilot — cards live in docs/ssot/kanban/cards/, rendered by scripts/render-board.py</p>
  </main>
</body>
</html>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page)
    print(f"wrote {out_path} ({len(cards)} cards)")


if __name__ == "__main__":
    sys.exit(main())
