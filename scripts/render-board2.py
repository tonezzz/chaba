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
POLL_SECONDS = 10

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
    #ny-body {{ max-height:34vh; overflow-y:auto; }}
    #detail pre {{ white-space:pre-wrap; }}
    #live-dot.tick {{ animation:dotblip .8s ease-out; }}
    @keyframes dotblip {{ 0%{{transform:scale(1.8);}} 100%{{transform:scale(1);}} }}
    .tab.doing-hot {{ animation:dpulse 1.6s infinite; }}
    @keyframes dpulse {{ 0%{{box-shadow:0 0 0 0 rgba(16,163,127,.55);}} 70%{{box-shadow:0 0 0 9px rgba(16,163,127,0);}} 100%{{box-shadow:0 0 0 0 rgba(16,163,127,0);}} }}
    .row.just-moved {{ animation:mvflash 1.8s ease-out; }}
    @keyframes mvflash {{ 0%{{background:#16457f;border-color:#38bdf8;}} 100%{{background:transparent;}} }}
    #ticker {{ position:fixed;left:0;right:0;bottom:0;height:26px;z-index:40;display:flex;align-items:center;background:#0d1b3a;border-top:1px solid #274a8c; }}
    .tk-label {{ font-size:10px;color:#7dd3fc;letter-spacing:1px;padding:0 10px;border-right:1px solid #274a8c;white-space:nowrap; }}
    .tk-view {{ flex:1;overflow:hidden; }}
    .tk-track {{ display:inline-block;white-space:nowrap;animation:tkscroll 80s linear infinite; }}
    .tk-item {{ font-size:11px;color:#c7d2fe;padding:0 14px; }}
    .tk-item b {{ color:#93c5fd; }}
    .tk-sep {{ color:#3b82f6;font-size:8px; }}
    @keyframes tkscroll {{ from{{transform:translateX(0);}} to{{transform:translateX(-50%);}} }}
    @media (max-width: 860px) {{
      #sidebar {{ width:100% !important; }}
      #detail {{ display:none; }}
      #detail.open {{ display:block; position:fixed; inset:0; background:#1a1a2e; z-index:50; overflow-y:auto; padding:12px; }}
    }}
  </style>
</head>
<body class="bg-bg text-slate-100 min-h-screen flex flex-col" style="height:100vh">
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

  <div id="needs-you" class="px-3"></div>

  <div class="flex gap-3 p-3 pb-8 flex-1 min-h-0">
    <div id="sidebar" class="flex flex-col gap-2 shrink-0" style="width:320px;min-width:240px">
      <input id="q" type="search" placeholder="Filter cards…"
        class="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm w-full">
      <div id="list" class="flex-1 overflow-y-auto space-y-1.5 pr-1 min-h-0"></div>
    </div>
    <div id="detail" class="flex-1 overflow-y-auto min-h-0 bg-slate-900/40 border border-slate-700/60 rounded-lg p-4"></div>
  </div>

  <div id="ticker"><div class="tk-label">事件流</div><div class="tk-view"><div class="tk-track" id="tk-track"></div></div></div>

<script>
const API = '/apps/board-api';
const POLL = {POLL_SECONDS} * 1000;
let DATA = null, tab = localStorage.getItem('b2-tab') || 'review';
let queries = JSON.parse(localStorage.getItem('b2-queries') || '{{}}');
let sel = localStorage.getItem('b2-sel') || null;
let autoOpen = JSON.parse(localStorage.getItem('b2-auto') || '{{}}');
let nyCollapsed = false;
try {{ nyCollapsed = localStorage.getItem('b2-ny-collapsed') === '1'; }} catch (e) {{}}
// 'cardId|reqId' -> {{answer, at}} — answers posted this session, replayed
// onto stale polls until the served cards.json regen confirms them
const pendingAns = {{}};
// same keys — row shows "✓ answered" briefly before dropping off the band
const nyFlash = {{}};
// 上轮轮询后刚换列/新入板的卡片 id -> 新列名，行闪烁提示；每次 load 前重置
const movedIn = {{}};
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
  const hay = ((c.title||'')+' '+c.id+' '+(c.brief||'')+' '+(c.note||'')+' '+(c.program||'')).toLowerCase();
  return q.toLowerCase().split(/\\s+/).every(w => hay.includes(w));
}}
// card-level ask — one standing decision per card, schema
// ask: {{question, options[]}} (board-structured-responses). Option
// buttons post {{id, option: N}}; the Other input posts {{id, text}} —
// both to /respond with no request_id.
function askOf(c) {{
  const a = c.ask;
  if (a && typeof a === 'object') return a;
  if (a) return {{question: String(a)}};
  return null;
}}
function askOpen(c) {{
  const a = askOf(c);
  return !!(a && a.question && a.status !== 'answered');
}}
function optLabel(o) {{ return typeof o === 'string' ? o : (o.label || o.id); }}
function needYou(c) {{
  return (c.requests||[]).filter(r => r.status !== 'answered').length
       + (askOpen(c) ? 1 : 0);
}}

function badgeHtml(c) {{
  let b = '';
  const p = (c.priority||'').toLowerCase();
  if (p === 'high') b += `<span class="badge bg-red-800/80 text-red-100">high</span> `;
  const ny = needYou(c);
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
  const brief1 = (c.brief || '').split('\\n')[0];
  const tip = esc(c.brief || '').replace(/"/g, '&quot;');
  const mv = movedIn[c.id];
  return `<div class="row board-card${{mv ? ' just-moved' : ''}} cursor-pointer border border-slate-700/60 rounded p-2 bg-slate-800/40" data-id="${{esc(c.id)}}"${{c.brief ? ` title="${{tip}}"` : ''}}>` +
    `<div class="text-sm leading-snug">${{esc(c.title)}}</div>` +
    (brief1 ? `<div class="text-[11px] text-slate-400 truncate mt-0.5">${{esc(brief1)}}</div>` : '') +
    `<div class="flex items-center gap-1 mt-1 flex-wrap"><span class="text-[10px] text-slate-500">${{esc(c.id)}}</span> ${{mv ? `<span class="badge bg-sky-800/80 text-sky-100">⇄ ${{esc(mv)}}</span> ` : ''}}${{badgeHtml(c)}}</div>` +
    `</div>`;
}}

function renderTabs() {{
  const counts = {{}};
  for (const c of DATA.cards) counts[c.column||'backlog'] = (counts[c.column||'backlog']||0)+1;
  counts.lab = DATA.cards.filter(isLab).length;
  let ny = 0; for (const c of DATA.cards) ny += needYou(c);
  const el = document.getElementById('ny-pill');
  el.textContent = ny + ' need you';
  el.classList.toggle('hidden', !ny);
  document.getElementById('tabs').innerHTML = TABS.map(t =>
    `<button class="tab text-xs px-3 py-1.5 rounded bg-slate-800/70 hover:bg-slate-700 ${{t.id===tab?'active':''}}${{t.id==='doing'&&(counts.doing||0)?' doing-hot':''}}" data-tab="${{t.id}}">` +
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
  renderNeedsYou();
  renderDetail();
  wireReq();
}}

// answer controls shared by the detail pane and the needs-tony band —
// every element carries data-id so one binder (wireReq) works for both
function reqAnswerHtml(c, r) {{
  const opts = r.options || [];
  if (opts.length) {{
    let h = '<div class="flex flex-wrap gap-1.5 mt-1.5 ml-4">';
    for (const o of opts) {{
      const lbl = typeof o === 'string' ? o : (o.label || o.id);
      const val = typeof o === 'string' ? o : (o.id + ' — ' + (o.label || ''));
      const sug = r.suggested && (r.suggested === val || r.suggested === lbl || (typeof o !== 'string' && r.suggested === o.id));
      h += `<button class="rq-opt text-xs ${{sug?'bg-emerald-800 hover:bg-emerald-700 ring-1 ring-emerald-400 font-semibold':'bg-amber-800/70 hover:bg-amber-700'}} rounded px-2 py-1" data-id="${{esc(c.id)}}" data-rq="${{esc(r.id)}}" data-val="${{esc(val)}}">${{sug?'★ ':''}}${{esc(lbl)}}</button>`;
    }}
    h += `<input class="rq-in flex-1 min-w-[100px] bg-slate-900 border border-slate-700 rounded px-1.5 py-1 text-xs" data-id="${{esc(c.id)}}" data-rq="${{esc(r.id)}}" placeholder="other…">`;
    h += `<button class="rq-btn text-xs bg-slate-700 hover:bg-slate-600 rounded px-2" data-id="${{esc(c.id)}}" data-rq="${{esc(r.id)}}">↵</button></div>`;
    return h;
  }}
  return `<div class="flex gap-1.5 mt-1.5 ml-4"><input class="rq-in flex-1 bg-slate-900 border border-slate-700 rounded px-1.5 py-1 text-xs" data-id="${{esc(c.id)}}" data-rq="${{esc(r.id)}}" placeholder="your answer…">` +
         `<button class="rq-btn text-xs bg-slate-700 hover:bg-slate-600 rounded px-2" data-id="${{esc(c.id)}}" data-rq="${{esc(r.id)}}">Answer</button></div>`;
}}

function reqHtml(c, r) {{
  let h = `<div class="mt-2"><div class="text-amber-300 text-sm">❓ ${{esc(r.ask)}}</div>`;
  if (r.status === 'answered') return h + `<div class="text-emerald-300 text-sm ml-4">→ ${{esc(r.answer)}}</div></div>`;
  return h + reqAnswerHtml(c, r) + '</div>';
}}

function askAnswerHtml(c) {{
  const a = askOf(c) || {{}};
  const opts = a.options || [];
  const sug = a.suggested || '';
  const isSug = o => sug && (sug === optLabel(o) || (typeof o !== 'string' && (sug === o.id || sug === `${{o.id}} — ${{o.label || ''}}`)));
  let h = '<div class="flex flex-wrap gap-1.5 mt-1.5 ml-4">';
  opts.forEach((o, i) => {{
    const s = isSug(o);
    h += `<button class="ask-opt text-xs ${{s ? 'bg-emerald-800 hover:bg-emerald-700 ring-1 ring-emerald-400 font-semibold' : 'bg-amber-800/70 hover:bg-amber-700'}} rounded px-2 py-1" data-id="${{esc(c.id)}}" data-opt="${{i}}">${{s ? '★ ' : ''}}${{esc(optLabel(o))}}</button>`;
  }});
  h += `<input class="ask-in flex-1 min-w-[100px] bg-slate-900 border border-slate-700 rounded px-1.5 py-1 text-xs" data-id="${{esc(c.id)}}" placeholder="other…">` +
       `<button class="ask-btn text-xs bg-slate-700 hover:bg-slate-600 rounded px-2" data-id="${{esc(c.id)}}">↵</button></div>`;
  return h;
}}

function askHtml(c) {{
  const a = askOf(c);
  if (!a) return '';
  let h = `<div class="mt-2"><div class="text-amber-300 text-sm">❓ ${{esc(a.question)}}</div>`;
  if (a.status === 'answered') return h + `<div class="text-emerald-300 text-sm ml-4">→ ${{esc(a.answer || '')}}</div></div>`;
  return h + askAnswerHtml(c) + '</div>';
}}

// 'Needs Tony' band — every open request/ask across all cards in one
// pass. Rows carry the same controls as the detail pane; a click posts
// /respond, flashes "✓ answered", then the row drops (board-decisions-inbox).
function nyItems() {{
  const items = [];
  for (const c of (DATA ? DATA.cards : [])) {{
    for (const r of c.requests || [])
      // nyFlash rows just answered this session stay mounted so the
      // "✓ answered" state is visible before the row drops
      if (r.status !== 'answered' || nyFlash[c.id + '|' + r.id])
        items.push({{c, r}});
    if (askOpen(c) || nyFlash[c.id + '|ask']) items.push({{c, ask: true}});
  }}
  return items;
}}

function nyItemHtml(it) {{
  const c = it.c;
  const key = c.id + '|' + (it.ask ? 'ask' : it.r.id);
  const head = `<button class="ny-card text-xs font-medium text-sky-300 hover:text-sky-200 underline underline-offset-2" data-id="${{esc(c.id)}}">${{esc(c.title || c.id)}}</button>` +
    `<span class="text-[10px] text-slate-500">${{esc(c.id)}} · ${{esc(c.column || 'backlog')}}</span>`;
  if (nyFlash[key])
    return `<div class="border border-emerald-700/50 rounded p-2 bg-emerald-950/30">` +
      `<div class="flex items-baseline gap-2 flex-wrap">${{head}}</div>` +
      `<div class="text-xs text-emerald-300 mt-1">✓ ${{esc(it.ask ? askOf(c).question : it.r.ask)}} → ${{esc((pendingAns[key] || {{}}).answer || '')}}</div></div>`;
  const askLine = `<div class="text-xs text-amber-200 mt-1">❓ ${{esc(it.ask ? askOf(c).question : it.r.ask)}}</div>`;
  const ctrl = it.ask ? askAnswerHtml(c) : reqAnswerHtml(c, it.r);
  return `<div class="border border-amber-700/40 rounded p-2 bg-amber-950/30">` +
    `<div class="flex items-baseline gap-2 flex-wrap">${{head}}</div>${{askLine}}${{ctrl}}</div>`;
}}

function renderNeedsYou() {{
  const el = document.getElementById('needs-you');
  // preserve in-progress free-text answers + focus across the poll tick
  const vals = {{}};
  let focus = null;
  el.querySelectorAll('.rq-in,.ask-in').forEach(i => {{
    const k = i.dataset.id + '|' + (i.dataset.rq || 'ask');
    vals[k] = i.value;
    if (document.activeElement === i) focus = k;
  }});
  const items = nyItems();
  if (!items.length) {{
    el.innerHTML = '<div class="text-[11px] text-slate-600 italic pb-1">✓ no pending decisions</div>';
    return;
  }}
  const n = items.filter(it => !nyFlash[it.c.id + '|' + (it.ask ? 'ask' : it.r.id)]).length;
  el.innerHTML =
    `<div class="bg-amber-900/40 border border-amber-600/60 rounded mb-1">` +
    `<button id="ny-toggle" class="w-full text-left px-2.5 py-1.5 text-amber-100 text-sm flex items-center gap-2">` +
    `<span id="ny-caret">${{nyCollapsed ? '▸' : '▾'}}</span>` +
    `<b>Needs Tony — ${{n}} open decision${{n === 1 ? '' : 's'}}</b>` +
    `<span class="ml-auto text-[10px] text-amber-200/60">★ = suggested, one click</span></button>` +
    `<div id="ny-body" class="px-2.5 pb-2.5 space-y-2${{nyCollapsed ? ' hidden' : ''}}">` +
    items.map(nyItemHtml).join('') + '</div></div>';
  document.getElementById('ny-toggle').onclick = () => {{
    nyCollapsed = !nyCollapsed;
    try {{ localStorage.setItem('b2-ny-collapsed', nyCollapsed ? '1' : '0'); }} catch (e) {{}}
    document.getElementById('ny-body').classList.toggle('hidden', nyCollapsed);
    document.getElementById('ny-caret').textContent = nyCollapsed ? '▸' : '▾';
  }};
  el.querySelectorAll('.rq-in,.ask-in').forEach(i => {{
    const k = i.dataset.id + '|' + (i.dataset.rq || 'ask');
    if (k in vals) {{
      i.value = vals[k];
      if (focus === k) {{ i.focus(); i.setSelectionRange(i.value.length, i.value.length); }}
    }}
  }});
}}

// record a successful /respond: flag it so stale polls can't resurrect
// the row, update the in-memory copy, flash the band row, then drop it
function markAnswered(cid, rid, answer) {{
  const key = cid + '|' + rid;
  pendingAns[key] = {{answer, at: Date.now()}};
  nyFlash[key] = true;
  const c = DATA && DATA.cards.find(x => x.id === cid);
  if (c) {{
    if (rid === 'ask') {{
      const a = askOf(c);
      if (a) {{ a.status = 'answered'; a.answer = answer; }}
    }} else {{
      const r = (c.requests || []).find(x => String(x.id) === String(rid));
      if (r) {{ r.status = 'answered'; r.answer = answer; }}
    }}
  }}
  toast('answer saved: ' + answer);
  renderTabs(); renderList();
  setTimeout(() => {{ delete nyFlash[key]; renderNeedsYou(); wireReq(); }}, 1600);
}}

// cards.json regen lags a /respond write by up to a render tick — replay
// locally recorded answers onto stale reads; drop confirmed/expired keys
function healPending() {{
  const t = Date.now();
  for (const [k, v] of Object.entries(pendingAns)) {{
    const i = k.indexOf('|');
    const c = DATA.cards.find(x => x.id === k.slice(0, i));
    const rid = k.slice(i + 1);
    let confirmed = false;
    if (c) {{
      if (rid === 'ask') {{
        const a = askOf(c);
        if (a && a.status === 'answered') confirmed = true;
        else if (a) {{ a.status = 'answered'; a.answer = v.answer; }}
      }} else {{
        const r = (c.requests || []).find(x => String(x.id) === rid);
        if (r && r.status === 'answered') confirmed = true;
        else if (r) {{ r.status = 'answered'; r.answer = v.answer; }}
      }}
    }}
    if (confirmed || t - v.at > 10 * 60e3) delete pendingAns[k];
  }}
}}

// one binder for every request/ask control — band rows and the detail
// pane share markup (.rq-*/.ask-* with data-id), so this binds both.
// onclick assignment is idempotent: safe to re-run after every render.
function wireReq() {{
  document.querySelectorAll('.rq-opt').forEach(b => b.onclick = async e => {{
    e.stopPropagation();
    const r = await api('/respond', {{id: b.dataset.id, request_id: b.dataset.rq, answer: b.dataset.val}});
    if (r && r.ok === false) {{ toast(r.error || 'refused'); return; }}
    markAnswered(b.dataset.id, b.dataset.rq, b.dataset.val);
  }});
  document.querySelectorAll('.rq-btn').forEach(b => b.onclick = async e => {{
    e.stopPropagation();
    const inp = b.parentElement.querySelector('.rq-in');
    if (!inp || !inp.value.trim()) return;
    const r = await api('/respond', {{id: b.dataset.id, request_id: b.dataset.rq, answer: inp.value.trim()}});
    if (r && r.ok === false) {{ toast(r.error || 'refused'); return; }}
    markAnswered(b.dataset.id, b.dataset.rq, inp.value.trim());
  }});
  document.querySelectorAll('.ask-opt').forEach(b => b.onclick = async e => {{
    e.stopPropagation();
    const r = await api('/respond', {{id: b.dataset.id, option: Number(b.dataset.opt)}});
    if (r && r.ok === false) {{ toast(r.error || 'refused'); return; }}
    markAnswered(b.dataset.id, 'ask', b.textContent.trim().replace(/^★ /, ''));
  }});
  document.querySelectorAll('.ask-btn').forEach(b => b.onclick = async e => {{
    e.stopPropagation();
    const inp = b.parentElement.querySelector('.ask-in');
    if (!inp || !inp.value.trim()) return;
    const r = await api('/respond', {{id: b.dataset.id, text: inp.value.trim()}});
    if (r && r.ok === false) {{ toast(r.error || 'refused'); return; }}
    markAnswered(b.dataset.id, 'ask', inp.value.trim());
  }});
  document.querySelectorAll('.rq-in,.ask-in').forEach(inp => inp.onkeydown = e => {{
    if (e.key !== 'Enter') return;
    e.stopPropagation();
    const b = inp.parentElement.querySelector('.rq-btn,.ask-btn');
    if (b) b.click();
  }});
  // card-title link in a band row — jump to the card's tab + detail pane
  document.querySelectorAll('.ny-card').forEach(b => b.onclick = () => {{
    const c = DATA && DATA.cards.find(x => x.id === b.dataset.id);
    if (c) {{ tab = isLab(c) ? 'lab' : (c.column || 'backlog'); localStorage.setItem('b2-tab', tab); }}
    sel = b.dataset.id; localStorage.setItem('b2-sel', sel);
    history.replaceState(null, '', '#tab=' + tab + '&card=' + sel);
    renderTabs(); renderList();
  }});
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
      ${{!['queued','running','done'].includes(a.status||'idle') && (a.type || !['doing','done','verified','review'].includes(c.column||'')) ? `<button class="act text-xs bg-sky-700 hover:bg-sky-600 rounded px-2.5 py-1" data-do="queue" title="queue for dispatch — repo defaults to chaba unless action.repo is set">▶ Start</button>`:''}}
      ${{c.column !== 'done' ? `<button class="act text-xs bg-emerald-800 hover:bg-emerald-700 rounded px-2.5 py-1" data-do="close">✓ close</button>`:''}}
      <select class="mv text-xs bg-slate-800 border border-slate-700 rounded px-2 py-1">
        <option value="">move to…</option>
        ${{(DATA.columns||[]).map(x=>`<option ${{x.id===c.column?'selected':''}}>${{esc(x.id)}}</option>`).join('')}}
      </select>
    </div></div>`;
  if (c.brief) h += `<div class="mt-3 border-l-4 border-sky-400 bg-sky-900/25 rounded-r px-3 py-2">` +
    `<div class="text-[10px] uppercase tracking-wide text-sky-300/80 mb-0.5">In plain terms</div>` +
    `<div class="text-[15px] leading-snug text-sky-50 whitespace-pre-wrap">${{esc(c.brief)}}</div></div>`;
  if ((c.lab||{{}}).hypothesis) h += field('🧪 hypothesis', c.lab.hypothesis) + field('metric', c.lab.metric) + field('outcome', c.lab.outcome);
  h += field('note', c.note) + field('spec', c.spec) + field('verify', c.verify) + field('help', c.help);
  if (askOf(c)) h += askHtml(c);
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
  // .rq-*/.ask-* controls (detail pane AND needs-tony band) are bound
  // once at the end of renderList via wireReq() — data-id carries the card
  document.getElementById('cm-btn').onclick = async () => {{
    const inp = document.getElementById('cm');
    if (!inp.value.trim()) return;
    await api('/comment', {{id: c.id, from: 'tony', text: inp.value.trim()}});
    toast('comment added'); await load();
  }};
  wireReq(); // select() reaches renderDetail without renderList — bind here too
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
  nyCollapsed = false;
  renderNeedsYou(); wireReq();
  document.getElementById('needs-you').scrollIntoView({{behavior:'smooth', block:'start'}});
}};
// ?decisions=1 deep-link (report/notifier surfaces) — open the band once
let decisionsLink = new URLSearchParams(location.search).has('decisions');

// 底部事件流：取全卡 comms 最近 30 条滚动展示；内容不变时不动 DOM，
// 让 -50% 无缝循环动画持续跑
function renderTicker() {{
  const items = [];
  for (const c of (DATA ? DATA.cards : [])) for (const m of (c.comms || [])) {{
    items.push({{at: m.at || m.ts || '', id: c.id, from: m.from || m.who || '', text: m.text || m.msg || ''}});
  }}
  items.sort((a, b) => String(b.at).localeCompare(String(a.at)));
  const top = items.slice(0, 30);
  const track = document.getElementById('tk-track');
  if (!track) return;
  let html;
  if (!top.length) {{
    html = '<span class="tk-item" style="opacity:.5">— 暂无事件 —</span>';
  }} else {{
    html = top.map(it =>
      `<span class="tk-item"><b>${{esc(it.at)}}</b> ${{esc(it.id)}} · ${{esc(it.from)}} · ${{esc(it.text)}}</span><span class="tk-sep">◆</span>`).join('');
  }}
  if (track.dataset.sig === html) return;
  track.dataset.sig = html;
  track.innerHTML = top.length ? html + html : html;
  track.style.animationDuration = Math.max(30, top.length * 3) + 's';
}}

async function load() {{
  try {{
    const r = await fetch('cards.json?t=' + Date.now(), {{cache:'no-store'}});
    const prevCols = {{}};
    if (DATA) for (const pc of DATA.cards) prevCols[pc.id] = pc.column || 'backlog';
    const j = await r.json();
    for (const k in movedIn) delete movedIn[k];
    if (Object.keys(prevCols).length) for (const c of j.cards || []) {{
      const nc = c.column || 'backlog';
      if (!(c.id in prevCols) || prevCols[c.id] !== nc) movedIn[c.id] = nc;
    }}
    DATA = j;
    healPending();
    document.getElementById('gen').textContent = 'v' + (DATA.page_version||'') + ' · ' + (DATA.generated||'');
    const m = location.hash.match(/tab=(\\w+)/); if (m) tab = m[1];
    const cm = location.hash.match(/card=([\\w-]+)/); if (cm) sel = cm[1];
    renderTabs(); renderList(); renderTicker();
    const dot = document.getElementById('live-dot');
    dot.className = 'w-2 h-2 rounded-full bg-emerald-400';
    dot.classList.remove('tick'); void dot.offsetWidth; dot.classList.add('tick');
    if (decisionsLink) {{
      decisionsLink = false; nyCollapsed = false;
      renderNeedsYou(); wireReq();
      document.getElementById('needs-you').scrollIntoView({{block:'start'}});
    }}
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
