#!/usr/bin/env python3
"""Render the kanban board: ssot.kanban.yml + cards/*.yml -> cards.json + index.html.

Layout follows the CMS page standard (ada-pi/pwa/cms/index.html):
nav bar with EN/ไทย toggle + refresh, filterable card sidebar, main
board pane, italic provenance footer. Document-first: edit a card file,
re-run this script, commit.

The page is dynamic: it fetches cards.json (served next to index.html)
on load and every POLL_SECONDS so card edits appear without a reload.
Buttons post to /apps/board-api/ (Caddy -> board-api.service on tony-dell),
which writes back into the card YAML and re-runs this renderer.

Usage: render-board.py [--if-changed]   (--if-changed skips when the
card-dir manifest hash is unchanged — cheap for the 60s timer run.)
"""
import hashlib
import html
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "docs/ssot/kanban/ssot.kanban.yml"
STATE = REPO / "docs/ssot/kanban/.render-state"
POLL_SECONDS = 30

I18N = {
    "board": ("Board", "บอร์ด"),
    "cards": ("Cards", "การ์ด"),
    "filter": ("Filter cards…", "ค้นหาการ์ด…"),
    "wip": ("WIP limit exceeded", "งานค้างเกินลิมิต"),
}


def esc(v) -> str:
    return html.escape(str(v))


def dir_hash(card_dir: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(card_dir.glob("*.yml")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def load_cards(man: dict) -> list:
    card_dir = REPO / man["card_dir"]
    cards = []
    for p in sorted(card_dir.glob("*.yml")):
        c = yaml.safe_load(p.read_text())
        c.setdefault("id", p.stem)
        cards.append(c)
    return cards


def main():
    man = yaml.safe_load(MANIFEST.read_text())
    card_dir = REPO / man["card_dir"]
    out_path = REPO / man["board_output"]

    if "--if-changed" in sys.argv:
        h = dir_hash(card_dir)
        if STATE.exists() and STATE.read_text().strip() == h and out_path.exists():
            return 0
        STATE.write_text(h + "\n")

    cards = load_cards(man)
    cols = man["columns"]
    limit = man.get("rules", {}).get("doing_limit", 2)
    doing_sessions = {}
    for c in cards:
        s = (c.get("claim") or {}).get("session")
        if c.get("column") == "doing" and s:
            doing_sessions[s] = doing_sessions.get(s, 0) + 1
    over = [s for s, n in doing_sessions.items() if n > limit]

    ts = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M")

    payload = {
        "generated": ts,
        "columns": cols,
        "doing_limit": limit,
        "over_limit": over,
        "cards": cards,
    }
    json_path = out_path.with_name("cards.json")
    json_path.write_text(json.dumps(payload, ensure_ascii=False))

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
    .board-cols {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }}
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
    <span id="live-dot" class="w-2 h-2 rounded-full bg-emerald-400" title="live"></span>
    <div class="ml-auto flex items-center gap-1">
      <button id="lang-en" class="text-xs px-2 py-1 rounded">EN</button>
      <button id="lang-th" class="text-xs px-2 py-1 rounded">ไทย</button>
    </div>
    <button id="btn-refresh" class="text-xs px-2 py-1 rounded bg-slate-700 hover:bg-slate-600">Refresh</button>
  </nav>

  <div id="toast" class="fixed bottom-4 right-4 bg-slate-800 border border-slate-600 rounded px-3 py-2 text-sm hidden z-50 max-w-sm"></div>

  <div id="card-modal" class="fixed inset-0 bg-black/70 hidden items-center justify-center z-40 flex">
    <div class="bg-card border border-slate-700 rounded-xl p-5 w-11/12 max-w-xl max-h-[85vh] overflow-y-auto" id="card-modal-body"></div>
  </div>

  <div id="help-modal" class="fixed inset-0 bg-black/70 hidden items-center justify-center z-50 flex">
    <div class="bg-card border border-slate-700 rounded-xl p-5 w-11/12 max-w-lg">
      <div class="flex items-center justify-between mb-3">
        <h3 id="help-title" class="font-semibold text-sm"></h3>
        <button id="help-close" class="text-xs px-2 py-1 rounded bg-slate-700 hover:bg-slate-600">Close</button>
      </div>
      <pre id="help-body" class="text-xs text-slate-300 whitespace-pre-wrap font-sans"></pre>
    </div>
  </div>

  <div class="max-w-6xl mx-auto p-4 md:flex md:gap-6 board-shell">
    <aside class="md:w-64 shrink-0 mb-6 md:mb-0 board-aside">
      <div class="flex items-center gap-2 mb-2">
        <h2 class="text-xs uppercase tracking-wide text-slate-500 i18n" data-en="Cards" data-th="การ์ด">Cards</h2>
        <button id="btn-toggle-list" class="md:hidden ml-auto text-xs px-2 py-1 rounded bg-slate-700 hover:bg-slate-600">Cards ▾</button>
      </div>
      <input id="card-filter" type="search" placeholder="Filter cards…"
             class="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm mb-2">
      <div id="card-list" class="space-y-1 text-sm hidden md:block"></div>
    </aside>
    <main class="flex-1 min-w-0 board-main">
      <div id="needs-you"></div>
      <div id="wip-warn"></div>
      <div id="board-cols" class="board-cols pb-4"></div>
      <p id="gen-note" class="text-xs text-slate-500 italic"></p>
    </main>
  </div>

<script>
const API = '/apps/board-api';
const POLL_MS = {POLL_SECONDS} * 1000;
let DATA = null;
let lang = 'en';
let filter_q = '';
let openCard = null;
let busy = false;

const esc = s => String(s == null ? '' : s)
  .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
  .replace(/"/g,'&quot;');

let toastTimer = null;
function toast(msg, isErr) {{
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'fixed bottom-4 right-4 rounded px-3 py-2 text-sm z-50 max-w-sm border ' +
    (isErr ? 'bg-red-900/90 border-red-500 text-red-100' : 'bg-slate-800 border-slate-600 text-slate-200');
  t.classList.remove('hidden');
  if (toastTimer) clearTimeout(toastTimer);
  if (!isErr) toastTimer = setTimeout(() => t.classList.add('hidden'), 3000);
}}
document.addEventListener('click', e => {{
  const t = document.getElementById('toast');
  if (e.target === t) t.classList.add('hidden');
}});

async function api(path, body) {{
  const r = await fetch(API + path, {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(body),
  }});
  const j = await r.json().catch(() => ({{}}));
  if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
  return j;
}}

function actBtns(c) {{
  const a = c.action || {{}};
  const st = a.status || 'idle';
  let h = '';
  if (st === 'queued')
    h += `<button class="abtn text-xs bg-amber-700 hover:bg-amber-600 rounded px-2 py-0.5" data-id="${{esc(c.id)}}" data-do="hold">⏳ queued — cancel</button>`;
  else if (st === 'running')
    h += `<span class="text-xs bg-sky-800/70 text-sky-200 rounded px-1.5 py-0.5">⚙ running${{a.task_id ? ' ' + esc(a.task_id.slice(0,20)) : ''}}</span>`;
  else if (st === 'done')
    h += `<button class="abtn text-xs bg-emerald-800 hover:bg-emerald-700 text-white rounded px-2 py-0.5" data-id="${{esc(c.id)}}" data-do="close">✔ Close</button>` +
         `<button class="abtn text-xs bg-slate-700 hover:bg-slate-600 rounded px-2 py-0.5" data-id="${{esc(c.id)}}" data-do="retry">↺ retry</button>`;
  else if (st === 'failed')
    h += `<button class="abtn text-xs bg-red-800 hover:bg-red-700 text-white rounded px-2 py-0.5" data-id="${{esc(c.id)}}" data-do="retry">↺ Retry</button>`;
  else
    h += `<button class="abtn text-xs bg-accent hover:opacity-90 text-white rounded px-2 py-0.5" data-id="${{esc(c.id)}}" data-do="queue">${{esc(a.button || '▶ Start')}}</button>`;
  return h;
}}

function reqList(c, inModal) {{
  const reqs = c.requests || [];
  if (!reqs.length) return '';
  let h = '';
  for (const r of reqs) {{
    if (r.status === 'answered')
      h += `<div class="text-xs text-slate-400 mt-1">❓ ${{esc(r.ask)}} <span class="text-emerald-300">→ ${{esc(r.answer)}}</span></div>`;
    else {{
      h += `<div class="text-xs text-amber-300 mt-1">❓ ${{esc(r.ask)}}</div>`;
      if (inModal)
        h += `<div class="flex gap-1 mt-0.5"><input class="rq-in flex-1 bg-slate-900 border border-slate-700 rounded px-1.5 py-1 text-xs" data-rq="${{esc(r.id)}}" placeholder="your answer…">` +
             `<button class="rq-btn text-xs bg-slate-700 hover:bg-slate-600 rounded px-2" data-rq="${{esc(r.id)}}">Answer</button></div>`;
    }}
  }}
  return h;
}}

function commsList(c) {{
  const log = c.comms || [];
  if (!log.length) return '';
  let h = '<div class="space-y-1">';
  for (const m of log.slice(-20))
    h += `<div class="text-xs"><span class="text-slate-500">${{esc(m.at || '')}}</span> ` +
         `<span class="${{m.from === 'tony' ? 'text-emerald-300' : m.from === 'devin' ? 'text-sky-300' : m.from === 'ada' ? 'text-fuchsia-300' : 'text-slate-300'}} font-medium">${{esc(m.from)}}:</span> ${{esc(m.text)}}</div>`;
  return h + '</div>';
}}

function cardHtml(c) {{
  const claim = c.claim || {{}};
  let badges = '';
  if (claim.session)
    badges += `<span class="text-xs bg-sky-800/70 text-sky-200 rounded px-1.5 py-0.5">⚙ ${{esc(claim.session)}}</span> `;
  if (c.blocked_by)
    badges += `<span class="text-xs bg-red-900/60 text-red-200 rounded px-1.5 py-0.5">blocked: ${{esc(c.blocked_by)}}</span> `;
  const openReqs = (c.requests || []).filter(r => r.status !== 'answered').length;
  if (openReqs)
    badges += `<span class="text-xs bg-amber-800/80 text-amber-100 rounded px-1.5 py-0.5">needs you ×${{openReqs}}</span> `;
  const a = c.action || {{}};
  const st = a.status || 'idle';
  if (st === 'queued') badges += '<span class="text-xs bg-amber-800/70 text-amber-200 rounded px-1.5 py-0.5">⏳ queued</span> ';
  else if (st === 'running') badges += '<span class="text-xs bg-sky-700/80 text-sky-100 rounded px-1.5 py-0.5">⚙ running</span> ';
  else if (st === 'failed') badges += '<span class="text-xs bg-red-800/70 text-red-100 rounded px-1.5 py-0.5">✖ failed</span> ';

  return `<div class="board-card bg-card border border-slate-700 rounded-lg p-3 mb-2 cursor-pointer hover:border-slate-500" data-id="${{esc(c.id)}}" data-text="${{esc(((c.title||'')+' '+c.id).toLowerCase())}}">` +
    `<div class="font-medium text-sm">${{esc(c.title || c.id)}}</div>` +
    (badges ? `<div class="mt-1.5 flex flex-wrap gap-1">${{badges}}</div>` : '') +
    `<div class="text-xs text-slate-400 mt-1.5">${{esc(c.note || '')}}</div>` +
    `<div class="text-[10px] text-slate-500 mt-1">${{esc(c.id)}} · ${{esc(c.updated || '')}}</div>` +
    '</div>';
}}

function render() {{
  if (!DATA) return;
  const counts = {{}};
  for (const c of DATA.cards) counts[c.column || 'backlog'] = (counts[c.column || 'backlog'] || 0) + 1;

  let cols = '';
  for (const col of DATA.columns) {{
    let body = '';
    for (const c of DATA.cards) if ((c.column || 'backlog') === col.id) body += cardHtml(c);
    if (!body) body = '<div class="text-slate-500 text-sm italic">—</div>';
    cols += `<div><div class="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">` +
      `<span class="col-title" data-en="${{esc(col.title)}}" data-th="${{esc(col.title)}}">${{esc(col.title)}}</span> · ${{counts[col.id] || 0}}</div>` +
      `<div class="bg-slate-800/40 border border-slate-700/60 rounded-lg p-2 min-h-[80px]">${{body}}</div></div>`;
  }}
  document.getElementById('board-cols').innerHTML = cols;

  // needs-you strip
  const needy = DATA.cards.filter(c => (c.requests || []).some(r => r.status !== 'answered'));
  document.getElementById('needs-you').innerHTML = needy.length
    ? `<div class="bg-amber-900/40 border border-amber-600/60 rounded p-2.5 mb-3 text-amber-100 text-sm flex flex-wrap items-center gap-2">` +
      `<b>Needs you (${{needy.length}}):</b>` +
      needy.map(c => `<button class="ny-btn text-xs bg-amber-800/70 hover:bg-amber-700 rounded px-2 py-0.5" data-id="${{esc(c.id)}}">${{esc(c.title || c.id)}}</button>`).join('') +
      '</div>'
    : '';

  let list = '';
  for (const col of DATA.columns) {{
    list += `<div class="text-[10px] uppercase tracking-wide text-slate-500 mt-3 mb-1">${{esc(col.title)}}</div>`;
    let any = false;
    for (const c of DATA.cards) if ((c.column || 'backlog') === col.id) {{
      any = true;
      list += `<div class="side-card px-2 py-1.5 rounded hover:bg-slate-800 cursor-pointer text-slate-300 truncate" data-id="${{esc(c.id)}}" data-text="${{esc(((c.title||'')+' '+c.id).toLowerCase())}}">${{esc(c.title || c.id)}}</div>`;
    }}
    if (!any) list += '<div class="text-slate-600 text-xs px-2">—</div>';
  }}
  document.getElementById('card-list').innerHTML = list;

  document.getElementById('wip-warn').innerHTML = (DATA.over_limit || []).length
    ? `<div class="bg-amber-900/50 border border-amber-600 rounded p-3 mb-4 text-amber-200 text-sm">WIP limit exceeded (doing > ${{DATA.doing_limit}}/session): ${{esc(DATA.over_limit.join(', '))}}</div>`
    : '';
  document.getElementById('gen-note').textContent =
    `Rendered ${{DATA.generated}} — cards in docs/ssot/kanban/cards/ · live (polls ${{POLL_SECONDS}}s)`;

  wire();
  setLang(lang);
  applyFilter();
  if (openCard) showCard(openCard);   // keep the open modal fresh
}}

function showCard(id) {{
  const c = DATA.cards.find(x => x.id === id);
  const modal = document.getElementById('card-modal');
  const body = document.getElementById('card-modal-body');
  if (!c) {{ modal.classList.add('hidden'); openCard = null; return; }}
  openCard = id;
  const claim = c.claim || {{}};
  const a = c.action || {{}};
  const colBtns = DATA.columns.filter(col => col.id !== (c.column || 'backlog'))
    .map(col => `<button class="mv-btn text-xs bg-slate-700 hover:bg-slate-600 rounded px-2 py-1" data-col="${{col.id}}">→ ${{esc(col.title)}}</button>`).join('');
  body.innerHTML =
    `<div class="flex items-start justify-between gap-3 mb-2">` +
      `<h3 class="font-semibold">${{esc(c.title || c.id)}}</h3>` +
      `<button id="cm-close" class="text-xs px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 shrink-0">✕</button></div>` +
    `<div class="text-[10px] text-slate-500 mb-3">${{esc(c.id)}} · ${{esc(c.column || 'backlog')}} · ${{esc(c.updated || '')}}${{claim.session ? ' · ⚙ ' + esc(claim.session) : ''}}${{a.runner ? ' · ran on ' + esc(a.runner) : ''}}</div>` +
    (c.note ? `<div class="text-sm text-slate-300 mb-3">${{esc(c.note)}}</div>` : '') +
    `<div class="flex flex-wrap gap-1.5 mb-3">${{actBtns(c)}}${{c.help ? `<button id="cm-help" class="text-xs bg-slate-700 hover:bg-slate-600 rounded px-2 py-1">? help</button>` : ''}}</div>` +
    `<div class="flex flex-wrap gap-1.5 mb-4">${{colBtns}}</div>` +
    (c.spec ? `<div class="mb-3"><div class="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Spec</div><pre class="text-xs text-slate-300 whitespace-pre-wrap font-sans border-l-2 border-slate-600 pl-2">${{esc(c.spec)}}</pre></div>` : '') +
    ((c.requests || []).length ? `<div class="mb-3"><div class="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Requests</div>${{reqList(c, true)}}</div>` : '') +
    ((c.comms || []).length ? `<div class="mb-3"><div class="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Comms</div>${{commsList(c)}}</div>` : '') +
    `<div class="flex gap-1.5 mt-4 border-t border-slate-700/60 pt-3">` +
      `<input id="cm-comment" class="flex-1 bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-xs" placeholder="comment on this card…">` +
      `<button id="cm-send" class="text-xs bg-slate-700 hover:bg-slate-600 rounded px-3">Send</button></div>`;

  document.getElementById('cm-close').onclick = () => {{ modal.classList.add('hidden'); openCard = null; }};
  modal.onclick = e => {{ if (e.target === modal) {{ modal.classList.add('hidden'); openCard = null; }} }};
  if (c.help) document.getElementById('cm-help').onclick = () => openHelp(c.title || c.id, c.help);
  document.getElementById('cm-send').onclick = async () => {{
    const inp = document.getElementById('cm-comment');
    if (!inp.value.trim()) return;
    try {{ await api('/comment', {{id, from: 'tony', text: inp.value.trim()}}); toast('comment added'); await load(); }}
    catch (e) {{ toast('error: ' + e.message, true); }}
  }};
  document.getElementById('cm-comment').onkeydown = e => {{ if (e.key === 'Enter') document.getElementById('cm-send').click(); }};
  modal.classList.remove('hidden');
}}

async function doAct(id, verb, extra) {{
  if (busy) return;
  busy = true;
  try {{
    const r = await api('/action', Object.assign({{id, do: verb}}, extra || {{}}));
    toast(r.message || 'ok');
    await load();
  }} catch (e) {{ toast('error: ' + e.message, true); }}
  busy = false;
}}

function wire() {{
  document.querySelectorAll('.board-card,.side-card').forEach(el =>
    el.onclick = e => {{ if (!e.target.closest('button,input')) showCard(el.dataset.id); }});
  document.querySelectorAll('.abtn').forEach(b =>
    b.onclick = e => {{ e.stopPropagation(); doAct(b.dataset.id, b.dataset.do); }});
  document.querySelectorAll('.mv-btn').forEach(b =>
    b.onclick = e => {{ e.stopPropagation(); doAct(openCard, 'move', {{column: b.dataset.col}}); }});
  document.querySelectorAll('.ny-btn').forEach(b =>
    b.onclick = () => showCard(b.dataset.id));
  document.querySelectorAll('.rq-btn').forEach(b =>
    b.onclick = async e => {{
      e.stopPropagation();
      const inp = document.querySelector(`.rq-in[data-rq="${{b.dataset.rq}}"]`);
      if (!inp || !inp.value.trim()) return;
      try {{ await api('/respond', {{id: openCard, request_id: b.dataset.rq, answer: inp.value.trim()}}); toast('answer saved'); await load(); }}
      catch (err) {{ toast('error: ' + err.message, true); }}
    }});
}}

function applyFilter() {{
  const q = filter_q.toLowerCase();
  document.querySelectorAll('.board-card,.side-card').forEach(el => {{
    el.style.display = el.dataset.text.includes(q) ? '' : 'none';
  }});
}}

async function load() {{
  try {{
    const r = await fetch('cards.json?t=' + Date.now());
    DATA = await r.json();
    document.getElementById('live-dot').className = 'w-2 h-2 rounded-full bg-emerald-400';
    render();
  }} catch (e) {{
    document.getElementById('live-dot').className = 'w-2 h-2 rounded-full bg-red-500';
  }}
}}

// static wiring
const filter = document.getElementById('card-filter');
filter.addEventListener('input', () => {{ filter_q = filter.value; applyFilter(); }});
document.getElementById('btn-toggle-list').onclick = () =>
  document.getElementById('card-list').classList.toggle('hidden');
document.getElementById('btn-refresh').onclick = () => load();
function setLang(l) {{
  lang = l;
  document.querySelectorAll('.i18n,.col-title').forEach(el => {{
    const v = el.dataset[l === 'th' ? 'th' : 'en'];
    if (v) el.textContent = v;
  }});
  document.getElementById('lang-en').className = 'text-xs px-2 py-1 rounded' + (l === 'en' ? ' bg-accent text-white' : ' bg-slate-700');
  document.getElementById('lang-th').className = 'text-xs px-2 py-1 rounded' + (l === 'th' ? ' bg-accent text-white' : ' bg-slate-700');
}}
document.getElementById('lang-en').onclick = () => setLang('en');
document.getElementById('lang-th').onclick = () => setLang('th');
const modal = document.getElementById('help-modal');
const openHelp = (title, body) => {{
  document.getElementById('help-title').textContent = title;
  document.getElementById('help-body').textContent = body;
  modal.classList.remove('hidden');
}};
document.getElementById('help-close').onclick = () => modal.classList.add('hidden');
modal.onclick = e => {{ if (e.target === modal) modal.classList.add('hidden'); }};
document.addEventListener('visibilitychange', () => {{ if (!document.hidden) load(); }});
document.addEventListener('keydown', e => {{
  if (e.key === 'Escape') {{
    document.getElementById('card-modal').classList.add('hidden'); openCard = null;
    document.getElementById('help-modal').classList.add('hidden');
  }}
}});

load();
setInterval(load, POLL_MS);
</script></script>
</body>
</html>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page)
    print(f"wrote {out_path} + cards.json ({len(cards)} cards)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
