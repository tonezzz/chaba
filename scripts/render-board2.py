#!/usr/bin/env python3
"""Render the tabbed kanban board view: same data as render-board.py,
different layout — Lab/Backlog/Doing/Review/Done tabs, each with its own
searchable card sidebar + detail pane. Writes board2/index.html +
board2/cards.json. Read-only alternative view for comparison; all write
actions go through the same /apps/board-api/ endpoints.

Usage: render-board2.py [--if-changed]
"""
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "docs/ssot/kanban/ssot.kanban.yml"
STATE = REPO / "docs/ssot/kanban/.render-state-board2"
POLL_SECONDS = 30

# reuse the data pipeline from render-board.py (same dir, dash filename)
_spec = importlib.util.spec_from_file_location(
    "render_board", REPO / "scripts/render-board.py")
_rb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_rb)

esc = _rb.esc


def main():
    man = yaml.safe_load(MANIFEST.read_text())
    card_dir = REPO / man["card_dir"]
    out_path = REPO / "stacks/web/public/apps/board2/index.html"

    if "--if-changed" in sys.argv:
        h = _rb.dir_hash(card_dir)
        if STATE.exists() and STATE.read_text().strip() == h and out_path.exists():
            return 0
        STATE.write_text(h + "\n")

    cards = _rb.load_cards(man)
    rank = {"high": 0, "medium": 1, "low": 3}
    cards.sort(key=lambda c: rank.get(str(c.get("priority") or "").lower(), 2))
    runs_by_slug = _rb._run_branches()
    outcomes = _rb._outcome_index()
    for c in cards:
        checks = _rb.compute_checks(c, runs_by_slug, outcomes)
        if checks:
            c["checks"] = checks
    limit = man.get("rules", {}).get("doing_limit", 2)

    ts = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M")

    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#1a1a2e">
  <title>Board — tabs</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    html {{ font-size: 18px; }}
    .bg-bg {{ background-color: #1a1a2e; }}
    .bg-card {{ background-color: #16213e; }}
    .tab.active {{ background:#0a84ff; color:#fff; }}
    .row.active {{ border-color:#0a84ff !important; background:#1e2b4d; }}
    .row:hover {{ background:#1c2a4a; }}
    .badge {{ font-size:10px; padding:1px 5px; border-radius:4px; }}
    #detail pre {{ white-space:pre-wrap; }}
    @media (max-width: 860px) {{
      #sidebar {{ width:100% !important; }}
      #detail {{ display:none; }}
      #detail.open {{ display:block; position:fixed; inset:0; background:#1a1a2e; z-index:50; overflow-y:auto; padding:12px; }}
    }}
  </style>
</head>
<body class="bg-bg text-slate-100 min-h-screen">
  <nav class="bg-card border-b border-slate-700 px-4 py-3 flex items-center gap-3">
    <a href="/apps/" class="text-sky-400 hover:text-sky-300">&larr; Apps</a>
    <span class="text-slate-500">|</span>
    <span class="font-semibold">Board <span class="text-xs text-slate-500">tabs view</span></span>
    <span id="live-dot" class="w-2 h-2 rounded-full bg-emerald-400" title="live"></span>
    <a href="/apps/board/" class="text-xs text-slate-400 hover:text-slate-200 underline underline-offset-2">classic view</a>
    <div class="ml-auto flex items-center gap-2">
      <span id="ny-pill" class="badge bg-amber-800/70 text-amber-100 px-2 py-0.5 rounded cursor-pointer hidden"></span>
      <span id="gen" class="text-[10px] text-slate-500"></span>
    </div>
  </nav>

  <div class="flex gap-2 px-3 pt-2 flex-wrap" id="tabs"></div>

  <div class="flex gap-3 p-3" style="height:calc(100vh - 120px)">
    <div id="sidebar" class="flex flex-col gap-2 shrink-0" style="width:320px;min-width:240px">
      <input id="q" type="search" placeholder="Filter cards…"
        class="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm w-full">
      <div id="list" class="flex-1 overflow-y-auto space-y-1.5 pr-1 min-h-0"></div>
    </div>
    <div id="detail" class="flex-1 overflow-y-auto min-h-0 bg-slate-900/40 border border-slate-700/60 rounded-lg p-4"></div>
  </div>

<script>
const API = '/apps/board-api';
const POLL = {POLL_SECONDS} * 1000;
let DATA = null, tab = localStorage.getItem('b2-tab') || 'review';
let queries = JSON.parse(localStorage.getItem('b2-queries') || '{{}}');
let sel = localStorage.getItem('b2-sel') || null;
let autoOpen = JSON.parse(localStorage.getItem('b2-auto') || '{{}}');
const AUTO_RE = /^(cms|logs|gev|vcast|disk)-auto-|-auto-health$/;

const TABS = [
  {{id:'lab',     title:'🧪 Lab'}},
  {{id:'backlog', title:'Backlog'}},
  {{id:'doing',   title:'Doing'}},
  {{id:'review',  title:'Review'}},
  {{id:'done',    title:'Done'}},
];

function esc(s) {{ const d=document.createElement('div'); d.textContent=String(s??''); return d.innerHTML; }}
function isLab(c) {{ return !!(c.lab && (c.lab.hypothesis || c.lab.metric || c.lab.outcome)); }}
function cardsFor(t) {{
  if (!DATA) return [];
  if (t === 'lab') return DATA.cards.filter(isLab).sort((a,b) => String((a.lab||{{}}).review_by||'~').localeCompare((b.lab||{{}}).review_by||'~'));
  return DATA.cards.filter(c => (c.column||'backlog') === t);
}}
function matchQ(c, q) {{
  if (!q) return true;
  const hay = ((c.title||'')+' '+c.id+' '+(c.note||'')+' '+(c.program||'')).toLowerCase();
  return q.toLowerCase().split(/\\s+/).every(w => hay.includes(w));
}}
function needYou(c) {{
  return (c.requests||[]).filter(r => r.status !== 'answered');
}}

function badgeHtml(c) {{
  let b = '';
  const p = (c.priority||'').toLowerCase();
  if (p === 'high') b += `<span class="badge bg-red-800/80 text-red-100">high</span> `;
  const ny = needYou(c).length;
  if (ny) b += `<span class="badge bg-amber-800/80 text-amber-100">❓${{ny}}</span> `;
  const lab = c.lab || {{}};
  if (lab.review_by) {{
    const od = !lab.outcome && lab.review_by < new Date().toISOString().slice(0,10);
    b += `<span class="badge ${{od?'bg-red-800/80 text-red-100':'bg-violet-800/70 text-violet-100'}}">🧪 ${{esc(lab.review_by)}}${{od?' ⚠':''}}</span> `;
  }}
  if (lab.outcome) b += `<span class="badge bg-violet-900/60 text-violet-200">🧪 ${{esc(lab.outcome)}}</span> `;
  const col = c.column || 'backlog';
  if (tab === 'lab' || tab === 'done') b += `<span class="badge bg-slate-700 text-slate-300">${{esc(col)}}</span> `;
  if (c.review_kind && col === 'review') b += `<span class="badge bg-sky-900/70 text-sky-200">${{esc(c.review_kind)}}</span> `;
  if ((c.checks||[]).some(x => x.state === 'fail')) b += `<span class="badge bg-red-900/80 text-red-200">✗ check</span> `;
  return b;
}}

function rowHtml(c) {{
  return `<div class="row board-card cursor-pointer border border-slate-700/60 rounded p-2 bg-slate-800/40" data-id="${{esc(c.id)}}">` +
    `<div class="text-sm leading-snug">${{esc(c.title)}}</div>` +
    `<div class="flex items-center gap-1 mt-1 flex-wrap"><span class="text-[10px] text-slate-500">${{esc(c.id)}}</span> ${{badgeHtml(c)}}</div>` +
    `</div>`;
}}

function renderTabs() {{
  const counts = {{}};
  for (const c of DATA.cards) counts[c.column||'backlog'] = (counts[c.column||'backlog']||0)+1;
  counts.lab = DATA.cards.filter(isLab).length;
  let ny = 0; for (const c of DATA.cards) ny += needYou(c).length;
  const el = document.getElementById('ny-pill');
  if (ny) {{ el.textContent = ny + ' need you'; el.classList.remove('hidden'); }}
  document.getElementById('tabs').innerHTML = TABS.map(t =>
    `<button class="tab text-xs px-3 py-1.5 rounded bg-slate-800/70 hover:bg-slate-700 ${{t.id===tab?'active':''}}" data-tab="${{t.id}}">` +
    `${{t.title}} <span class="opacity-70">${{counts[t.id]||0}}</span></button>`).join('');
  document.querySelectorAll('.tab').forEach(b => b.onclick = () => {{
    tab = b.dataset.tab; localStorage.setItem('b2-tab', tab);
    history.replaceState(null,'','#tab='+tab);
    renderTabs(); renderList();
  }});
}}

function renderList() {{
  const q = queries[tab] || '';
  if (document.getElementById('q').value !== q) document.getElementById('q').value = q;
  const all = cardsFor(tab);
  const norm = all.filter(c => !AUTO_RE.test(c.id));
  const autos = all.filter(c => AUTO_RE.test(c.id));
  const vis = norm.filter(c => matchQ(c, q));
  let html = vis.map(rowHtml).join('') || '<div class="text-slate-500 text-sm italic p-2">—</div>';
  const autoVis = autos.filter(c => matchQ(c, q));
  if (autoVis.length) {{
    const open = !!autoOpen[tab] || q !== '';
    html += `<div class="border border-slate-700/50 rounded p-2 opacity-75">` +
      `<div class="auto-tog text-xs text-slate-500 cursor-pointer select-none">${{open?'▾':'▸'}} automation (${{autoVis.length}})</div>` +
      (open ? `<div class="mt-1.5 space-y-1.5">${{autoVis.map(rowHtml).join('')}}</div>` : '') + '</div>';
  }}
  document.getElementById('list').innerHTML = html;
  document.querySelectorAll('.auto-tog').forEach(t => t.onclick = () => {{
    autoOpen[tab] = !autoOpen[tab]; localStorage.setItem('b2-auto', JSON.stringify(autoOpen)); renderList();
  }});
  document.querySelectorAll('.board-card').forEach(r => r.onclick = () => select(r.dataset.id));
  const selEl = document.querySelector(`.board-card[data-id="${{CSS.escape(sel||'')}}"]`);
  if (selEl) selEl.classList.add('active');
  renderDetail();
}}

function reqHtml(c, r) {{
  let h = `<div class="mt-2"><div class="text-amber-300 text-sm">❓ ${{esc(r.ask)}}</div>`;
  if (r.status === 'answered') return h + `<div class="text-emerald-300 text-sm ml-4">→ ${{esc(r.answer)}}</div></div>`;
  const opts = r.options || [];
  if (opts.length) {{
    h += '<div class="flex flex-wrap gap-1.5 mt-1.5 ml-4">';
    for (const o of opts) {{
      const lbl = typeof o === 'string' ? o : (o.label || o.id);
      const val = typeof o === 'string' ? o : (o.id + ' — ' + (o.label || ''));
      const sug = r.suggested && (r.suggested === val || r.suggested === lbl || (typeof o !== 'string' && r.suggested === o.id));
      h += `<button class="rq-opt text-xs ${{sug?'bg-emerald-800 hover:bg-emerald-700 ring-1 ring-emerald-400 font-semibold':'bg-amber-800/70 hover:bg-amber-700'}} rounded px-2 py-1" data-rq="${{esc(r.id)}}" data-val="${{esc(val)}}">${{sug?'★ ':''}}${{esc(lbl)}}</button>`;
    }}
    h += `<input class="rq-in flex-1 min-w-[100px] bg-slate-900 border border-slate-700 rounded px-1.5 py-1 text-xs" data-rq="${{esc(r.id)}}" placeholder="other…">`;
    h += `<button class="rq-btn text-xs bg-slate-700 hover:bg-slate-600 rounded px-2" data-rq="${{esc(r.id)}}">↵</button></div>`;
  }} else {{
    h += `<div class="flex gap-1.5 mt-1.5 ml-4"><input class="rq-in flex-1 bg-slate-900 border border-slate-700 rounded px-1.5 py-1 text-xs" data-rq="${{esc(r.id)}}" placeholder="your answer…">` +
         `<button class="rq-btn text-xs bg-slate-700 hover:bg-slate-600 rounded px-2" data-rq="${{esc(r.id)}}">Answer</button></div>`;
  }}
  return h + '</div>';
}}

function field(label, v) {{
  if (!v) return '';
  return `<div class="mt-3"><div class="text-[10px] uppercase tracking-wide text-slate-500 mb-1">${{label}}</div>` +
    `<div class="text-sm text-slate-200 whitespace-pre-wrap">${{esc(v)}}</div></div>`;
}}

function renderDetail() {{
  const el = document.getElementById('detail');
  const c = DATA && DATA.cards.find(x => x.id === sel);
  if (!c) {{ el.innerHTML = '<div class="text-slate-500 text-sm italic p-4">Select a card</div>'; return; }}
  const a = c.action || {{}};
  let h = `<div class="flex items-start gap-3">
    <div class="flex-1"><div class="text-lg font-semibold">${{esc(c.title)}}</div>
    <div class="text-xs text-slate-500 mt-0.5">${{esc(c.id)}} · ${{esc(c.column||'backlog')}} ${{c.priority?'· '+esc(c.priority):''}}</div>
    <div class="mt-1">${{badgeHtml(c)}}</div></div>
    <div class="flex flex-col gap-1 items-end shrink-0">
      ${{a.type === 'dispatch' && (a.status||'idle') !== 'done' ? `<button class="act text-xs bg-sky-700 hover:bg-sky-600 rounded px-2.5 py-1" data-do="queue">▶ Start</button>`:''}}
      ${{c.column !== 'done' ? `<button class="act text-xs bg-emerald-800 hover:bg-emerald-700 rounded px-2.5 py-1" data-do="close">✓ close</button>`:''}}
      <select class="mv text-xs bg-slate-800 border border-slate-700 rounded px-2 py-1">
        <option value="">move to…</option>
        ${{(DATA.columns||[]).map(x=>`<option ${{x.id===c.column?'selected':''}}>${{esc(x.id)}}</option>`).join('')}}
      </select>
    </div></div>`;
  if ((c.lab||{{}}).hypothesis) h += field('🧪 hypothesis', c.lab.hypothesis) + field('metric', c.lab.metric) + field('outcome', c.lab.outcome);
  h += field('note', c.note) + field('spec', c.spec) + field('verify', c.verify) + field('help', c.help);
  for (const r of (c.requests||[])) h += reqHtml(c, r);
  const log = (c.comms||[]).slice(-20);
  if (log.length) {{
    h += '<div class="mt-4"><div class="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Comms</div>' +
      log.map(m => `<div class="text-xs border-l-2 border-slate-700 pl-2 py-1"><span class="text-slate-500">${{esc(m.at||m.ts||'')}} · ${{esc(m.from||m.who||'')}}</span><br>${{esc(m.text||m.msg||'')}}</div>`).join('') + '</div>';
  }}
  h += `<div class="flex gap-1.5 mt-4"><input id="cm" class="flex-1 bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-xs" placeholder="comment…">` +
       `<button id="cm-btn" class="text-xs bg-slate-700 hover:bg-slate-600 rounded px-3">Post</button></div>`;
  el.innerHTML = h;
  el.classList.add('open');

  document.querySelectorAll('.act').forEach(b => b.onclick = async () => {{
    const r = await api('/action', {{id: c.id, do: b.dataset.do}});
    toast(r.ok === false ? (r.error || 'refused') : b.dataset.do + ' ok'); await load();
  }});
  document.querySelector('.mv').onchange = async (e) => {{
    if (!e.target.value || e.target.value === c.column) return;
    const r = await api('/action', {{id: c.id, do: 'move', column: e.target.value}});
    toast(r.ok === false ? (r.error || 'refused') : 'moved'); await load();
  }};
  document.querySelectorAll('.rq-opt').forEach(b => b.onclick = async () => {{
    const r = await api('/respond', {{id: c.id, request_id: b.dataset.rq, answer: b.dataset.val}});
    toast('answer saved'); await load();
  }});
  document.querySelectorAll('.rq-btn').forEach(b => b.onclick = async () => {{
    const inp = b.parentElement.querySelector('.rq-in');
    if (!inp.value.trim()) return;
    await api('/respond', {{id: c.id, request_id: b.dataset.rq, answer: inp.value.trim()}});
    toast('answer saved'); await load();
  }});
  document.getElementById('cm-btn').onclick = async () => {{
    const inp = document.getElementById('cm');
    if (!inp.value.trim()) return;
    await api('/comment', {{id: c.id, from: 'tony', text: inp.value.trim()}});
    toast('comment added'); await load();
  }};
}}

function select(id) {{
  sel = id; localStorage.setItem('b2-sel', id);
  history.replaceState(null,'','#tab='+tab+'&card='+id);
  document.querySelectorAll('.board-card').forEach(r => r.classList.toggle('active', r.dataset.id === id));
  renderDetail();
}}

async function api(path, body) {{
  try {{
    const r = await fetch(API + path, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify(body)}});
    return await r.json();
  }} catch (e) {{ return {{ok:false, error:String(e)}}; }}
}}

function toast(msg) {{
  const d = document.createElement('div');
  d.className = 'fixed bottom-3 right-3 bg-slate-800 border border-slate-600 rounded px-3 py-2 text-sm z-50';
  d.textContent = msg; document.body.appendChild(d);
  setTimeout(() => d.remove(), 2500);
}}

document.getElementById('q').oninput = (e) => {{
  queries[tab] = e.target.value;
  localStorage.setItem('b2-queries', JSON.stringify(queries));
  renderList();
}};
document.getElementById('ny-pill').onclick = () => {{
  tab = 'review'; localStorage.setItem('b2-tab','review'); renderTabs(); renderList();
}};

async function load() {{
  try {{
    const r = await fetch('cards.json?t=' + Date.now(), {{cache:'no-store'}});
    DATA = await r.json();
    document.getElementById('gen').textContent = 'v' + (DATA.page_version||'') + ' · ' + (DATA.generated||'');
    const m = location.hash.match(/tab=(\\w+)/); if (m) tab = m[1];
    const cm = location.hash.match(/card=([\\w-]+)/); if (cm) sel = cm[1];
    renderTabs(); renderList();
  }} catch (e) {{ document.getElementById('live-dot').className = 'w-2 h-2 rounded-full bg-red-500'; }}
}}
load(); setInterval(load, POLL);
</script>
</body>
</html>
"""

    ver = hashlib.sha256(page.encode()).hexdigest()[:12]
    payload = {
        "generated": ts,
        "page_version": ver,
        "columns": man["columns"],
        "doing_limit": limit,
        "cards": cards,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    json_path = out_path.with_name("cards.json")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, default=str))
    out_path.write_text(page)
    print(f"wrote {out_path} + cards.json ({len(cards)} cards, v{ver})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
