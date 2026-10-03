#!/usr/bin/env python3
"""Render the kanban board: ssot.kanban.yml + cards/*.yml -> static HTML.

Layout follows the CMS page standard (ada-pi/pwa/cms/index.html):
nav bar with EN/ไทย toggle + refresh, filterable card sidebar, main
board pane, italic provenance footer. Document-first: edit a card file,
re-run this script, commit.
"""
import html
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "docs/ssot/kanban/ssot.kanban.yml"

I18N = {
    "board": ("Board", "บอร์ด"),
    "cards": ("Cards", "การ์ด"),
    "filter": ("Filter cards…", "ค้นหาการ์ด…"),
    "empty": ("—", "—"),
    "wip": ("WIP limit exceeded", "งานค้างเกินลิมิต"),
    "session": ("session", "เซสชัน"),
    "blocked": ("blocked", "ติดขัด"),
}


def esc(v) -> str:
    return html.escape(str(v))


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
        s = (c.get("claim") or {}).get("session")
        if c.get("column") == "doing" and s:
            doing_sessions[s] = doing_sessions.get(s, 0) + 1
    over = [s for s, n in doing_sessions.items() if n > limit]

    # ---- board columns (main pane) ----
    col_html = ""
    for col in cols:
        body = ""
        for c in cards:
            if c.get("column") != col["id"]:
                continue
            claim = c.get("claim") or {}
            badges = ""
            if claim.get("session"):
                badges += (
                    '<span class="text-xs bg-sky-800/70 text-sky-200 rounded px-1.5 py-0.5">'
                    f'⚙ {esc(claim["session"])}</span> '
                )
            if c.get("blocked_by"):
                badges += (
                    '<span class="text-xs bg-red-900/60 text-red-200 rounded px-1.5 py-0.5">'
                    f'blocked: {esc(c["blocked_by"])}</span>'
                )
            note = esc(c.get("note", ""))
            body += (
                f'<div class="board-card bg-card border border-slate-700 rounded-lg p-3 mb-2" '
                f'data-text="{esc((c.get("title","")+" "+c["id"]).lower())}">'
                f'<div class="font-medium text-sm">{esc(c.get("title", c["id"]))}</div>'
                f'<div class="mt-1.5 flex flex-wrap gap-1">{badges}</div>'
                f'<div class="text-xs text-slate-400 mt-1.5">{note}</div>'
                f'<div class="text-[10px] text-slate-500 mt-1">{esc(c["id"])} · {esc(c.get("updated", ""))}</div>'
                "</div>"
            )
        if not body:
            body = '<div class="text-slate-500 text-sm italic">—</div>'
        col_html += (
            '<div class="flex-1 min-w-[230px]">'
            f'<div class="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">'
            f'<span class="col-title" data-en="{esc(col["title"])}" data-th="{esc(I18N.get(col["id"], (col["title"], col["title"]))[1] if col["id"] in I18N else col["title"])}">{esc(col["title"])}</span>'
            f' · {counts.get(col["id"], 0)}</div>'
            f'<div class="bg-slate-800/40 border border-slate-700/60 rounded-lg p-2 min-h-[80px]">{body}</div>'
            "</div>"
        )

    # ---- sidebar card list ----
    list_html = ""
    for col in cols:
        list_html += (
            f'<div class="text-[10px] uppercase tracking-wide text-slate-500 mt-3 mb-1">{esc(col["title"])}</div>'
        )
        for c in cards:
            if c.get("column") != col["id"]:
                continue
            list_html += (
                f'<div class="side-card px-2 py-1.5 rounded hover:bg-slate-800 cursor-default text-slate-300 truncate" '
                f'data-text="{esc((c.get("title","")+" "+c["id"]).lower())}">'
                f'{esc(c.get("title", c["id"]))}</div>'
            )
        if not any(c.get("column") == col["id"] for c in cards):
            list_html += '<div class="text-slate-600 text-xs px-2">—</div>'

    warn = ""
    if over:
        warn = (
            '<div class="bg-amber-900/50 border border-amber-600 rounded p-3 mb-4 text-amber-200 text-sm">'
            f'<span class="i18n" data-en="WIP limit exceeded" data-th="{esc(I18N["wip"][1])}">WIP limit exceeded</span>'
            f' (doing &gt; {limit}/session): {esc(", ".join(over))}</div>'
        )

    ts = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M")
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#1a1a2e">
  <title>Board</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    .bg-bg {{ background-color: #1a1a2e; }}
    .bg-card {{ background-color: #16213e; }}
    .bg-accent {{ background-color: #0a84ff; }}
    @media (min-width: 768px) {{
      .board-shell {{ height: calc(100vh - 110px); overflow: hidden; }}
      .board-aside {{ display: flex; flex-direction: column; min-height: 0; }}
      .board-aside #card-list {{ flex: 1; overflow-y: auto; min-height: 0; padding-right: 4px; }}
      .board-main {{ overflow-y: auto; min-height: 0; }}
      #btn-toggle-list {{ display: none; }}
    }}
  </style>
</head>
<body class="bg-bg text-slate-100 min-h-screen">
  <nav class="bg-card border-b border-slate-700 px-4 py-3 flex items-center gap-3">
    <a href="/apps/" class="text-sky-400 hover:text-sky-300">&larr; Apps</a>
    <span class="text-slate-500">|</span>
    <span class="font-semibold i18n" data-en="Board" data-th="บอร์ด">Board</span>
    <div class="ml-auto flex items-center gap-1">
      <button id="lang-en" class="text-xs px-2 py-1 rounded">EN</button>
      <button id="lang-th" class="text-xs px-2 py-1 rounded">ไทย</button>
    </div>
    <button id="btn-refresh" class="text-xs px-2 py-1 rounded bg-slate-700 hover:bg-slate-600">Refresh</button>
  </nav>

  <div class="max-w-6xl mx-auto p-4 md:flex md:gap-6 board-shell">
    <aside class="md:w-64 shrink-0 mb-6 md:mb-0 board-aside">
      <div class="flex items-center gap-2 mb-2">
        <h2 class="text-xs uppercase tracking-wide text-slate-500 i18n" data-en="Cards" data-th="การ์ด">Cards</h2>
        <button id="btn-toggle-list" class="md:hidden ml-auto text-xs px-2 py-1 rounded bg-slate-700 hover:bg-slate-600">Cards ▾</button>
      </div>
      <input id="card-filter" type="search" placeholder="Filter cards…"
             class="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm mb-2">
      <div id="card-list" class="space-y-1 text-sm hidden md:block">{list_html}</div>
    </aside>
    <main class="flex-1 min-w-0 board-main">
      {warn}
      <div class="flex gap-3 overflow-x-auto pb-4">{col_html}</div>
      <p class="text-xs text-slate-500 italic">Generated by render-board.py at {esc(ts)} — cards in docs/ssot/kanban/cards/</p>
    </main>
  </div>

<script>
  const filter = document.getElementById('card-filter');
  filter.addEventListener('input', () => {{
    const q = filter.value.toLowerCase();
    document.querySelectorAll('.board-card,.side-card').forEach(el => {{
      el.style.display = el.dataset.text.includes(q) ? '' : 'none';
    }});
  }});
  document.getElementById('btn-toggle-list').onclick = () =>
    document.getElementById('card-list').classList.toggle('hidden');
  document.getElementById('btn-refresh').onclick = () => location.reload();
  function setLang(l) {{
    document.querySelectorAll('.i18n,.col-title').forEach(el => {{
      const v = el.dataset[l === 'th' ? 'th' : 'en'];
      if (v) el.textContent = v;
    }});
    document.getElementById('lang-en').className = 'text-xs px-2 py-1 rounded' + (l === 'en' ? ' bg-accent text-white' : ' bg-slate-700');
    document.getElementById('lang-th').className = 'text-xs px-2 py-1 rounded' + (l === 'th' ? ' bg-accent text-white' : ' bg-slate-700');
  }}
  document.getElementById('lang-en').onclick = () => setLang('en');
  document.getElementById('lang-th').onclick = () => setLang('th');
  setLang('en');
</script>
</body>
</html>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page)
    print(f"wrote {out_path} ({len(cards)} cards)")


if __name__ == "__main__":
    sys.exit(main())
