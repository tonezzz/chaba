#!/usr/bin/env python3
"""Render the Planka-style kanban board view: same data as render-board.py,
different layout — Lab/Backlog/Doing/Review/Done as five side-by-side
columns (no tab navigation), zoom +/- cycling card density
compact|normal|full, drag-and-drop card moves via board-api /action
do=move, and a modal card detail overlay. Writes board2/index.html +
board2/cards.json. View layer only; all write actions go through the
same /apps/board-api/ endpoints.

Usage: render-board2.py [--if-changed]
"""
import hashlib
import importlib.util
import json
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "docs/ssot/kanban/ssot.kanban.yml"
STATE = REPO / "docs/ssot/kanban/.render-state-board2"
# card attachments (board-api /attach) live in the repo under
# docs/ssot/kanban/attachments/<card-id>/ — outside the web container's
# /srv/public mount, so each render mirrors them into the app dir where
# Caddy's file_server exposes them as attachments/<card-id>/<file>
ATTACH_SRC = REPO / "docs/ssot/kanban/attachments"
POLL_SECONDS = 10

# reuse the data pipeline from render-board.py (same dir, dash filename)
_spec = importlib.util.spec_from_file_location(
    "render_board", REPO / "scripts/render-board.py")
_rb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_rb)

esc = _rb.esc

# raw-string template — JS braces/escapes (\n, \s, \w) pass through
# unchanged; only __POLL_SECONDS__ is substituted
PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#1a1a2e">
  <title>Board</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    html { font-size: 18px; }
    .bg-bg { background-color: #1a1a2e; }
    .bg-card { background-color: #16213e; }
    .badge { font-size:12px; padding:1px 5px; border-radius:4px; white-space:nowrap; }
    #ny-body { max-height:34vh; overflow-y:auto; }
    #live-dot.tick { animation:dotblip .8s ease-out; }
    @keyframes dotblip { 0%{transform:scale(1.8);} 100%{transform:scale(1);} }
    .col.doing-hot .col-count { animation:dpulse 1.6s infinite; }
    @keyframes dpulse { 0%{box-shadow:0 0 0 0 rgba(16,163,127,.55);} 70%{box-shadow:0 0 0 9px rgba(16,163,127,0);} 100%{box-shadow:0 0 0 0 rgba(16,163,127,0);} }
    .card.just-moved { animation:mvflash 1.8s ease-out; }
    @keyframes mvflash { 0%{background:#16457f;border-color:#38bdf8;} 100%{background:transparent;} }

    /* ---- Planka-style columns ---- */
    #board { flex:1; min-height:0; display:flex; gap:10px; padding:10px 12px 34px; overflow-x:auto; }
    .col { flex:1 1 0; min-width:230px; max-width:420px; display:flex; flex-direction:column;
           background:#141c33; border:1px solid #232f52; border-radius:10px; min-height:0; }
    .col-head { display:flex; align-items:center; gap:6px; padding:7px 10px 5px;
                font-size:12px; font-weight:600; letter-spacing:.3px; color:#cbd5e1; }
    .col-count { margin-left:auto; font-size:10px; font-weight:600; background:#263356;
                 color:#93c5fd; border-radius:8px; padding:1px 7px; }
    .col-list { flex:1; min-height:0; overflow-y:auto; padding:2px 8px 8px; }
    .col.drop-hint { border-color:#38bdf8; background:#152238; }
    .col.drop-hint .col-head { color:#7dd3fc; }
    .col-nope { opacity:.35; }
    /* slim scrollbars — recover horizontal room on dense boards */
    * { scrollbar-width:thin; scrollbar-color:#33456b transparent; }
    *::-webkit-scrollbar { width:6px; height:6px; }
    *::-webkit-scrollbar-thumb { background:#33456b; border-radius:3px; }
    *::-webkit-scrollbar-track { background:transparent; }
    /* collapsed column -> slim vertical strip (title reads bottom-up) */
    .col-head { cursor:pointer; user-select:none; }
    .col.collapsed { flex:0 0 44px; min-width:44px; max-width:44px; }
    .col.collapsed .col-list { display:none; }
    .col.collapsed .col-head { writing-mode:vertical-rl; transform:rotate(180deg);
                               flex:1; justify-content:flex-start; align-items:center;
                               padding:10px 6px; gap:8px; }
    .col.collapsed .col-count { margin:0; }
    .col-tog { font-size:10px; color:#64748b; line-height:1; }
    .col.collapsed .col-tog { transform:rotate(90deg); }

    /* ---- tight card rows; density via #board class ---- */
    .card { cursor:pointer; border:1px solid #2a3a63; border-radius:7px; background:#1b2745;
            padding:5px 7px; margin-bottom:5px; }
    .card:hover { background:#22315a; }
    .card.dragging { opacity:.4; }
    .card .ttl { font-size:16px; line-height:1.3; }
    .card .meta { display:flex; align-items:center; gap:4px; margin-top:3px; flex-wrap:wrap; }
    .card .brief-line { display:none; font-size:13px; color:#94a3b8; margin-top:2px;
                        overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    /* compact: title + affordance chips only */
    #board.d-compact .card { padding:3px 6px; margin-bottom:3px; }
    #board.d-compact .card .ttl { font-size:14px; }
    #board.d-compact .card .meta { margin-top:1px; }
    #board.d-compact .card .chip-extra { display:none; }
    /* full: adds the brief first line */
    #board.d-full .card .brief-line { display:block; }
    .autobox { border:1px dashed #33415f; border-radius:7px; padding:4px 6px; opacity:.75; }
    .autobox .auto-tog { font-size:10.5px; color:#64748b; cursor:pointer; user-select:none; }
    .more-tog { font-size:10.5px; color:#64748b; cursor:pointer; user-select:none; padding:4px 6px; }

    /* ---- modal card view ---- */
    #overlay { position:fixed; inset:0; background:rgba(5,9,20,.72); z-index:60;
               display:none; align-items:flex-start; justify-content:center; padding:5vh 12px 8vh; }
    #overlay.open { display:flex; }
    #modal { width:100%; max-width:720px; max-height:88vh; overflow-y:auto;
             background:#141c33; border:1px solid #2f3f6b; border-radius:12px; padding:16px 18px; }
    #modal pre { white-space:pre-wrap; }
    #modal-x { line-height:1; }

    /* ---- card cycle control (read-only pane — KNB-0229 design) ---- */
    /* RED: the control section is deliberately vivid — it is the active
       surface Tony reads while cycling cards. */
    #control { background:#241212; border:1px solid #7f1d1d;
               border-left:4px solid #ef4444; border-radius:8px;
               padding:6px 12px 10px; margin:4px 8px 0; }
    .cp-head-small { font-size:10px; color:#fecaca; font-weight:600;
                     text-transform:uppercase; letter-spacing:.06em;
                     padding:2px 2px 6px; }
    #control .cp-title { color:#fde2e2; }
    .cp-card { margin-bottom:6px; }
    .cp-head { width:100%; text-align:left; background:none; border:1px solid #33415f;
               border-radius:8px; padding:6px 9px; color:#cbd5e1; font-size:13px; cursor:pointer;
               display:flex; align-items:center; gap:8px; }
    .cp-head:hover { border-color:#38bdf8; }
    .cp-caret { color:#64748b; min-width:12px; }
    .cp-title { flex:1; }
    .cp-st { font-size:9px; padding:1px 7px; border-radius:9px; white-space:nowrap; }
    .cp-st-idle { background:#334155; color:#94a3b8; }
    .cp-st-queued { background:#b4530940; color:#fbbf24; }
    .cp-st-running { background:#0e749040; color:#67e8f9; }
    .cp-st-done { background:#14532d60; color:#4ade80; }
    .cp-st-other { background:#374151; color:#94a3b8; }
    .cp-pane { margin-top:6px; display:grid; gap:10px; }
    .cp-sec { border-left:2px solid #33415f; padding:6px 10px; background:#0f1730;
              border-radius:0 6px 6px 0; }
    .cp-sec-t { font-size:10px; text-transform:uppercase; letter-spacing:.06em;
                color:#64748b; margin-bottom:4px; }
    .cp-rows { display:grid; grid-template-columns:auto 1fr; gap:2px 10px; font-size:12px; color:#cbd5e1; }
    .cp-rk { color:#64748b; font-size:11px; }
    .cp-rv { color:#e2e8f0; white-space:pre-wrap; word-break:break-word; min-width:0; }
    .cp-rv.muted { color:#64748b; font-style:italic; }
    .cp-hint { color:#64748b; font-size:10px; }
    .cp-tl { font-size:11px; color:#94a3b8; }
    .cp-tl b { color:#7dd3fc; }
    .cp-src { color:#475569; font-size:9px; font-style:italic; }

    /* ---- zoom + ticker ---- */
    .zoom-btn { width:24px; height:24px; border-radius:6px; background:#263356; color:#cbd5e1;
                font-size:14px; font-weight:700; display:inline-flex; align-items:center;
                justify-content:center; }
    .zoom-btn:hover { background:#31427a; }
    #density-lbl { font-size:10px; color:#64748b; min-width:52px; text-align:center; }
    #colmenu { position:absolute; top:44px; z-index:70; display:none; background:#16213e;
               border:1px solid #2f3f6b; border-radius:8px; padding:6px 10px; min-width:130px; }
    #colmenu.open { display:block; }
    #colmenu label { display:flex; align-items:center; gap:7px; font-size:12px;
                     color:#cbd5e1; padding:3px 0; cursor:pointer; white-space:nowrap; }
    #colmenu input { accent-color:#0a84ff; }
    #ticker { position:fixed;left:0;right:0;bottom:0;height:26px;z-index:40;display:flex;align-items:center;background:#0d1b3a;border-top:1px solid #274a8c; }
    .tk-label { font-size:10px;color:#7dd3fc;letter-spacing:1px;padding:0 10px;border-right:1px solid #274a8c;white-space:nowrap; }
    .tk-view { flex:1;overflow:hidden; }
    .tk-track { display:inline-block;white-space:nowrap;animation:tkscroll 80s linear infinite; }
    .tk-view:hover .tk-track { animation-play-state:paused; }
    .tk-item { font-size:11px;color:#c7d2fe;padding:0 14px; }
    .tk-item b { color:#93c5fd; }
    .tk-sep { color:#3b82f6;font-size:8px; }
    @keyframes tkscroll { from{transform:translateX(0);} to{transform:translateX(-50%);} }
    @media (max-width: 860px) {
      .col { min-width:78vw; }
      #overlay { padding:0; }
      #modal { max-width:none; max-height:100vh; min-height:100vh; border-radius:0; }
    }
  </style>
</head>
<body class="bg-bg text-slate-100 min-h-screen flex flex-col" style="height:100vh">
  <nav class="bg-card border-b border-slate-700 px-4 py-2.5 flex items-center gap-3">
    <a href="/apps/" class="text-sky-400 hover:text-sky-300">&larr; Apps</a>
    <span class="text-slate-500">|</span>
    <span class="font-semibold">Board</span>
    <span id="live-dot" class="w-2 h-2 rounded-full bg-emerald-400" title="live"></span>
    <input id="q" type="search" placeholder="Filter cards…"
      class="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-sm w-44 ml-2">
    <div class="flex items-center gap-1">
      <button id="z-out" class="zoom-btn" title="zoom out (denser)">&minus;</button>
      <span id="density-lbl">normal</span>
      <button id="z-in" class="zoom-btn" title="zoom in (roomier)">+</button>
    </div>
    <div class="relative">
      <button id="cols-btn" class="zoom-btn" title="show/hide columns" style="width:auto;padding:0 8px;font-size:12px">▦ columns</button>
      <div id="colmenu"></div>
    </div>
    <a href="archive.html" class="zoom-btn" style="width:auto;padding:0 8px;font-size:12px;text-decoration:none" title="archived done cards">🗄 archive</a>
    <div class="ml-auto flex items-center gap-2">
      <span id="ny-pill" class="badge bg-amber-800/70 text-amber-100 px-2 py-0.5 rounded cursor-pointer hidden"></span>
      <span id="gen" class="text-[10px] text-slate-500"></span>
    </div>
  </nav>

  <div id="needs-you" class="px-3 pt-2"></div>

  <div id="control"></div>

  <div id="board" class="d-normal"></div>

  <div id="overlay"><div id="modal">
    <div class="flex justify-end -mt-1 -mr-1 mb-1">
      <button id="modal-x" class="text-slate-500 hover:text-slate-200 text-lg px-2" title="close (Esc)">✕</button>
    </div>
    <div id="modal-body"></div>
  </div></div>

  <div id="ticker"><div class="tk-label">EVENTS</div><div class="tk-view"><div class="tk-track" id="tk-track"></div></div></div>

<script>
const API = '/apps/board-api';
const POLL = __POLL_SECONDS__ * 1000;
let DATA = null, sel = null;
let q = localStorage.getItem('b2-q') || '';
let autoOpen = JSON.parse(localStorage.getItem('b2-auto') || '{}');
// done-column paging — render first PAGE cards, expand on demand
const PAGE = 100;
let moreOpen = new Set(JSON.parse(localStorage.getItem('b2-more') || '[]'));
let density = localStorage.getItem('b2-density') || 'normal';
let nyCollapsed = false;
try { nyCollapsed = localStorage.getItem('b2-ny-collapsed') === '1'; } catch (e) {}
// 'cardId|reqId' -> {answer, at} — answers posted this session, replayed
// onto stale polls until the served cards.json regen confirms them
const pendingAns = {};
// same keys — row shows "✓ answered" briefly before dropping off the band
const nyFlash = {};
// card id -> new column name, set by the poll diff; rows flash blue
const movedIn = {};
// id of the card currently being dragged (null outside a drag)
let dragId = null;
const AUTO_RE = /^(cms|logs|gev|vcast|disk|runner|audit|cast|eye)-auto-|-auto-health$|^timer-alert-/;
const DENSITIES = ['compact', 'normal', 'full'];

const COLS = [
  {id:'lab',     title:'🧪 Lab'},
  {id:'backlog', title:'Backlog'},
  {id:'doing',   title:'Doing'},
  {id:'review',  title:'Review'},
  {id:'done',    title:'Done'},
];

function esc(s) { const d=document.createElement('div'); d.textContent=String(s??''); return d.innerHTML; }

// ---- card attachments (board-api /attach) ----
// comms entries carry the canonical repo path
// 'docs/ssot/kanban/attachments/<card-id>/<file>'; the render mirrors
// that tree next to this page, so the servable URL is attachments/<…>
const ATT_RE = /docs\/ssot\/kanban\/attachments\/([A-Za-z0-9._\/-]+)/g;
const ATT_IMG = /\.(jpe?g|png|gif|webp|avif|bmp|tiff?|heic|heif)$/i;
function attachLinks(text) {
  const out = [];
  ATT_RE.lastIndex = 0;
  let m;
  while ((m = ATT_RE.exec(String(text ?? '')))) {
    const rel = m[1].replace(/[./]+$/, '');
    if (rel) out.push(rel);
  }
  return out;
}
function cardAttach(c) {
  // unique attachment paths across the card's comms, first-seen order
  const seen = new Set();
  for (const m of (c.comms || [])) for (const rel of attachLinks(m.text || m.msg || '')) seen.add(rel);
  return [...seen];
}
function attachUrl(rel) {
  return 'attachments/' + rel.split('/').map(encodeURIComponent).join('/');
}
function thumbHtml(rel) {
  const url = attachUrl(rel);
  const nm = rel.split('/').pop();
  return ATT_IMG.test(nm)
    ? `<a href="${url}" target="_blank" rel="noopener" title="${esc(nm)}"><img src="${url}" loading="lazy" alt="${esc(nm)}" class="h-20 w-auto max-w-[140px] object-cover rounded border border-slate-600 hover:border-sky-400"></a>`
    : `<a href="${url}" target="_blank" rel="noopener" title="${esc(nm)}" class="text-xs bg-slate-800 border border-slate-600 rounded px-2 py-1 text-sky-300 hover:text-sky-200">📎 ${esc(nm)}</a>`;
}
function attachHtml(text) {
  const links = attachLinks(text);
  if (!links.length) return '';
  return '<div class="flex flex-wrap gap-1.5 mt-1">' + links.map(thumbHtml).join('') + '</div>';
}

function isLab(c) { return !!(c.lab && (c.lab.hypothesis || c.lab.metric || c.lab.outcome)); }
// lab stays a virtual lane: lab cards appear there (sorted by review_by)
// AND in their real column — same semantics the tabs had
function cardsFor(t) {
  if (!DATA) return [];
  if (t === 'lab') return DATA.cards.filter(isLab).sort((a,b) => String((a.lab||{}).review_by||'~').localeCompare((b.lab||{}).review_by||'~'));
  const hit = DATA.cards.filter(c => (c.column||'backlog') === t);
  // done sorts freshest-first so recent closes surface on top;
  // other columns keep board order (rank/priority semantics)
  if (t === 'done') hit.sort((a,b) => String(b.updated||'').localeCompare(String(a.updated||'')));
  return hit;
}
function matchQ(c, qq) {
  if (!qq) return true;
  const hay = ((c.title||'')+' '+c.id+' '+(c.ref||'')+' '+(c.brief||'')+' '+(c.note||'')+' '+(c.program||'')).toLowerCase();
  return qq.toLowerCase().split(/\s+/).every(w => hay.includes(w));
}
// card-level ask — one standing decision per card, schema
// ask: {question, options[]} (board-structured-responses). Option
// buttons post {id, option: N}; the Other input posts {id, text} —
// both to /respond with no request_id.
function askOf(c) {
  const a = c.ask;
  if (a && typeof a === 'object') return a;
  if (a) return {question: String(a)};
  return null;
}
function askOpen(c) {
  const a = askOf(c);
  return !!(a && a.question && a.status !== 'answered');
}
// options may be {id,label}, {v,d} (value/description shorthand), or a
// bare string — tolerate all three so a non-canonical card can't blank out
function optLabel(o) { return typeof o === 'string' ? o : (o.label || o.d || o.id || o.v || ''); }
function optVal(o) { if (typeof o === 'string') return o; const k = o.id || o.v; return k ? k + ' — ' + (o.label || o.d || '') : (o.label || o.d || ''); }
function needYou(c) {
  return (c.requests||[]).filter(r => r.status !== 'answered').length
       + (askOpen(c) ? 1 : 0);
}

// ctx = the column this row is rendered in (a lab card shows its real
// column chip when sitting in the lab lane)
function badgeHtml(c, ctx) {
  let b = '';
  const p = (c.priority||'').toLowerCase();
  if (p === 'high') b += `<span class="badge bg-red-800/80 text-red-100">high</span> `;
  const lab = c.lab || {};
  if (lab.review_by) {
    const od = !lab.outcome && lab.review_by < new Date().toISOString().slice(0,10);
    b += `<span class="badge ${od?'bg-red-800/80 text-red-100':'bg-violet-800/70 text-violet-100'}">🧪 ${esc(lab.review_by)}${od?' ⚠':''}</span> `;
  }
  if (lab.outcome) b += `<span class="badge bg-violet-900/60 text-violet-200">🧪 ${esc(lab.outcome)}</span> `;
  const col = c.column || 'backlog';
  if (ctx === 'lab' || ctx === 'done') b += `<span class="badge bg-slate-700 text-slate-300">${esc(col)}</span> `;
  if (c.review_kind && col === 'review') b += `<span class="badge bg-sky-900/70 text-sky-200">${esc(c.review_kind)}</span> `;
  if ((c.checks||[]).some(x => x.state === 'fail')) b += `<span class="badge bg-red-900/80 text-red-200">✗ check</span> `;
  return b;
}

// tight row: title + label chips + comment/request affordances
function rowHtml(c, ctx) {
  const brief1 = (c.brief || '').split('\n')[0];
  const tip = esc(c.brief || '').replace(/"/g, '&quot;');
  const mv = movedIn[c.id];
  const ny = needYou(c);
  const ncm = (c.comms || []).length;
  const nat = cardAttach(c).length;
  return `<div class="card${mv ? ' just-moved' : ''}" draggable="true" data-id="${esc(c.id)}"${c.brief ? ` title="${tip}"` : ''}>` +
    `<div class="ttl">${esc(c.title)}</div>` +
    (brief1 ? `<div class="brief-line">${esc(brief1)}</div>` : '') +
    `<div class="meta"><span class="chip-extra text-[9px] text-slate-500">${c.ref?`<b class="text-sky-400 font-semibold">${esc(c.ref)}</b> `:''}${esc(c.id)}</span>` +
    (mv ? `<span class="badge bg-sky-800/80 text-sky-100">⇄ ${esc(mv)}</span> ` : '') +
    `<span class="chip-extra">${badgeHtml(c, ctx)}</span>` +
    (nat ? `<span class="badge bg-slate-700/80 text-slate-300" title="attachments">📎${nat}</span> ` : '') +
    (ny ? `<span class="badge bg-amber-800/80 text-amber-100" title="open requests/asks">❓${ny}</span> ` : '') +
    (ncm ? `<span class="badge bg-slate-700/80 text-slate-300" title="comments">💬${ncm}</span>` : '') +
    `</div></div>`;
}

function colHtml(col) {
  const all = cardsFor(col.id);
  const norm = all.filter(c => !AUTO_RE.test(c.id));
  const autos = all.filter(c => AUTO_RE.test(c.id));
  let vis = norm.filter(c => matchQ(c, q));
  let moreRow = '';
  if (col.id === 'done' && q === '' && !moreOpen.has('done')
      && vis.length > PAGE) {
    moreRow = `<div class="more-tog" data-col="done">▸ show ${vis.length - PAGE} more</div>`;
    vis = vis.slice(0, PAGE);
  } else if (col.id === 'done' && moreOpen.has('done') && q === ''
      && norm.length > PAGE) {
    moreRow = `<div class="more-tog" data-col="done">▾ show less</div>`;
  }
  let inner = vis.map(c => rowHtml(c, col.id)).join('')
    || '<div class="text-slate-600 text-[11px] italic px-1 py-2">—</div>'
    + moreRow;
  const autoVis = autos.filter(c => matchQ(c, q));
  if (autoVis.length) {
    const open = !!autoOpen[col.id] || q !== '';
    inner += `<div class="autobox mt-1">` +
      `<div class="auto-tog" data-col="${col.id}">${open?'▾':'▸'} automation (${autoVis.length})</div>` +
      (open ? `<div class="mt-1">${autoVis.map(c => rowHtml(c, col.id)).join('')}</div>` : '') + '</div>';
  }
  const hot = col.id === 'doing' && all.length > 0;
  const nVis = vis.length + autoVis.length;
  const cl = collapsedCols.has(col.id) ? ' collapsed' : '';
  return `<div class="col${cl}${hot ? ' doing-hot' : ''}${col.id === 'lab' ? ' col-virtual' : ''}" data-col="${col.id}">` +
    `<div class="col-head" title="click to ${cl ? 'expand' : 'collapse'}"><span>${col.title}</span>` +
    `<span class="col-count">${q ? nVis + '/' + all.length : all.length}</span>` +
    `<span class="col-tog">${cl ? '▸' : '▾'}</span></div>` +
    `<div class="col-list">${inner}</div></div>`;
}

// column visibility — hiddenCols persisted in localStorage; the board
// never lets the last visible column be hidden (the menu is the only way
// back, and it must stay reachable)
const hiddenCols = new Set(
  JSON.parse(localStorage.getItem('b2-cols') || '[]'));
function saveCols() {
  localStorage.setItem('b2-cols', JSON.stringify([...hiddenCols]));
}
// collapsed -> slim vertical strip (lighter than the ▦ hide menu — the
// column stays on board as a clickable handle)
const collapsedCols = new Set(
  JSON.parse(localStorage.getItem('b2-collapsed') || '[]'));
function saveCollapsed() {
  localStorage.setItem('b2-collapsed', JSON.stringify([...collapsedCols]));
}
function renderColMenu() {
  document.getElementById('colmenu').innerHTML = COLS.map(c =>
    `<label><input type="checkbox" data-col="${c.id}"${hiddenCols.has(c.id) ? '' : ' checked'}> ${esc(c.title)}</label>`
  ).join('');
}

function renderBoard() {
  if (document.getElementById('q').value !== q) document.getElementById('q').value = q;
  const visCols = COLS.filter(c => !hiddenCols.has(c.id));
  document.getElementById('board').innerHTML = visCols.map(colHtml).join('')
    || '<div class="text-slate-500 text-sm p-4 italic">all columns hidden — use the ▦ columns menu</div>';
  // ny pill — total open decisions across all cards
  let ny = 0; for (const c of (DATA ? DATA.cards : [])) ny += needYou(c);
  const el = document.getElementById('ny-pill');
  el.textContent = ny + ' need you';
  el.classList.toggle('hidden', !ny);
  wireBoard();
  renderNeedsYou();
  renderModal();
}

// column-head collapse — delegated once on #board so it survives poll
// re-renders: per-element onclick can die when innerHTML swaps between
// wiring and click (Tony 2026-10-22: clicks collapsed nothing).
document.getElementById('board').addEventListener('click', (e) => {
  const h = e.target.closest('.col-head');
  if (!h) return;
  const id = h.closest('.col').dataset.col;
  collapsedCols.has(id) ? collapsedCols.delete(id) : collapsedCols.add(id);
  saveCollapsed();
  renderBoard();
});

function wireBoard() {
  document.querySelectorAll('.card').forEach(r => {
    r.ondragstart = e => {
      dragId = r.dataset.id;
      e.dataTransfer.setData('text/plain', dragId);
      e.dataTransfer.effectAllowed = 'move';
      r.classList.add('dragging');
      document.querySelectorAll('.col').forEach(cl => {
        // lab is a virtual lane — not a real column to move into
        cl.classList.toggle('col-nope', cl.dataset.col === 'lab');
      });
    };
    r.ondragend = () => {
      dragId = null;
      r.classList.remove('dragging');
      document.querySelectorAll('.col').forEach(cl => cl.classList.remove('drop-hint', 'col-nope'));
    };
  });
  document.querySelectorAll('.col').forEach(cl => {
    cl.ondragover = e => {
      if (!dragId || cl.dataset.col === 'lab') return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      cl.classList.add('drop-hint');
    };
    cl.ondragleave = () => cl.classList.remove('drop-hint');
    cl.ondrop = async e => {
      e.preventDefault();
      cl.classList.remove('drop-hint');
      const id = e.dataTransfer.getData('text/plain') || dragId;
      const target = cl.dataset.col;
      dragId = null;
      if (!id || target === 'lab') return;
      const c = DATA && DATA.cards.find(x => x.id === id);
      if (!c || (c.column || 'backlog') === target) return;
      const r = await api('/action', {id, do:'move', column: target});
      toast(r && r.ok === false ? (r.error || 'refused') : `moved → ${target}`);
      await load();
    };
  });
}

// answer controls shared by the modal and the needs-tony band —
// every element carries data-id so the delegated click listener works for both
function reqAnswerHtml(c, r) {
  const opts = r.options || [];
  if (opts.length) {
    let h = '<div class="flex flex-wrap gap-1.5 mt-1.5 ml-4">';
    for (const o of opts) {
      const lbl = optLabel(o);
      const val = optVal(o);
      const sug = r.suggested && (r.suggested === val || r.suggested === lbl || (typeof o !== 'string' && (r.suggested === o.id || r.suggested === o.v)));
      h += `<button class="rq-opt text-xs ${sug?'bg-emerald-800 hover:bg-emerald-700 ring-1 ring-emerald-400 font-semibold':'bg-amber-800/70 hover:bg-amber-700'} rounded px-2 py-1" data-id="${esc(c.id)}" data-rq="${esc(r.id)}" data-val="${esc(val)}">${sug?'★ ':''}${esc(lbl)}</button>`;
    }
    h += `<input class="rq-in flex-1 min-w-[100px] bg-slate-900 border border-slate-700 rounded px-1.5 py-1 text-xs" data-id="${esc(c.id)}" data-rq="${esc(r.id)}" placeholder="other…">`;
    h += `<button class="rq-btn text-xs bg-slate-700 hover:bg-slate-600 rounded px-2" data-id="${esc(c.id)}" data-rq="${esc(r.id)}">↵</button></div>`;
    return h;
  }
  return `<div class="flex gap-1.5 mt-1.5 ml-4"><input class="rq-in flex-1 bg-slate-900 border border-slate-700 rounded px-1.5 py-1 text-xs" data-id="${esc(c.id)}" data-rq="${esc(r.id)}" placeholder="your answer…">` +
         `<button class="rq-btn text-xs bg-slate-700 hover:bg-slate-600 rounded px-2" data-id="${esc(c.id)}" data-rq="${esc(r.id)}">Answer</button></div>`;
}

function reqHtml(c, r) {
  let h = `<div class="mt-2"><div class="text-amber-300 text-sm">❓ ${esc(r.ask)}</div>`;
  if (r.status === 'answered') return h + `<div class="text-emerald-300 text-sm ml-4">→ ${esc(r.answer)}</div></div>`;
  return h + reqAnswerHtml(c, r) + '</div>';
}

function askAnswerHtml(c) {
  const a = askOf(c) || {};
  const opts = a.options || [];
  const sug = a.suggested || '';
  const isSug = o => sug && (sug === optLabel(o) || (typeof o !== 'string' && (sug === o.id || sug === o.v || sug === optVal(o))));
  let h = '<div class="flex flex-wrap gap-1.5 mt-1.5 ml-4">';
  opts.forEach((o, i) => {
    const s = isSug(o);
    h += `<button class="ask-opt text-xs ${s ? 'bg-emerald-800 hover:bg-emerald-700 ring-1 ring-emerald-400 font-semibold' : 'bg-amber-800/70 hover:bg-amber-700'} rounded px-2 py-1" data-id="${esc(c.id)}" data-opt="${i}">${s ? '★ ' : ''}${esc(optLabel(o))}</button>`;
  });
  h += `<input class="ask-in flex-1 min-w-[100px] bg-slate-900 border border-slate-700 rounded px-1.5 py-1 text-xs" data-id="${esc(c.id)}" placeholder="other…">` +
       `<button class="ask-btn text-xs bg-slate-700 hover:bg-slate-600 rounded px-2" data-id="${esc(c.id)}">↵</button></div>`;
  return h;
}

function askHtml(c) {
  const a = askOf(c);
  if (!a) return '';
  let h = `<div class="mt-2"><div class="text-amber-300 text-sm">❓ ${esc(a.question)}</div>`;
  if (a.status === 'answered') return h + `<div class="text-emerald-300 text-sm ml-4">→ ${esc(a.answer || '')}</div></div>`;
  return h + askAnswerHtml(c) + '</div>';
}

// 'Needs Tony' band — every open request/ask across all cards in one
// pass. Rows carry the same controls as the modal; a click posts
// /respond, flashes "✓ answered", then the row drops (board-decisions-inbox).
function nyItems() {
  const items = [];
  for (const c of (DATA ? DATA.cards : [])) {
    for (const r of c.requests || [])
      if (r.status !== 'answered' || nyFlash[c.id + '|' + r.id])
        items.push({c, r});
    if (askOpen(c) || nyFlash[c.id + '|ask']) items.push({c, ask: true});
  }
  return items;
}

function nyItemHtml(it) {
  const c = it.c;
  const key = c.id + '|' + (it.ask ? 'ask' : it.r.id);
  const head = `<button class="ny-card text-xs font-medium text-sky-300 hover:text-sky-200 underline underline-offset-2" data-id="${esc(c.id)}">${esc(c.title || c.id)}</button>` +
    `<span class="text-[10px] text-slate-500">${esc(c.id)} · ${esc(c.column || 'backlog')}</span>`;
  if (nyFlash[key])
    return `<div class="border border-emerald-700/50 rounded p-2 bg-emerald-950/30">` +
      `<div class="flex items-baseline gap-2 flex-wrap">${head}</div>` +
      `<div class="text-xs text-emerald-300 mt-1">✓ ${esc(it.ask ? askOf(c).question : it.r.ask)} → ${esc((pendingAns[key] || {}).answer || '')}</div></div>`;
  const askLine = `<div class="text-xs text-amber-200 mt-1">❓ ${esc(it.ask ? askOf(c).question : it.r.ask)}</div>`;
  const ctrl = it.ask ? askAnswerHtml(c) : reqAnswerHtml(c, it.r);
  return `<div class="border border-amber-700/40 rounded p-2 bg-amber-950/30">` +
    `<div class="flex items-baseline gap-2 flex-wrap">${head}</div>${askLine}${ctrl}</div>`;
}

function renderNeedsYou() {
  const el = document.getElementById('needs-you');
  // preserve in-progress free-text answers + focus across the poll tick
  const vals = {};
  let focus = null;
  el.querySelectorAll('.rq-in,.ask-in').forEach(i => {
    const k = i.dataset.id + '|' + (i.dataset.rq || 'ask');
    vals[k] = i.value;
    if (document.activeElement === i) focus = k;
  });
  const items = nyItems();
  if (!items.length) {
    el.innerHTML = '<div class="text-[11px] text-slate-600 italic pb-1">✓ no pending decisions</div>';
    return;
  }
  const n = items.filter(it => !nyFlash[it.c.id + '|' + (it.ask ? 'ask' : it.r.id)]).length;
  el.innerHTML =
    `<div class="bg-amber-900/40 border border-amber-600/60 rounded mb-1">` +
    `<button id="ny-toggle" class="w-full text-left px-2.5 py-1.5 text-amber-100 text-sm flex items-center gap-2">` +
    `<span id="ny-caret">${nyCollapsed ? '▸' : '▾'}</span>` +
    `<b>Needs Tony — ${n} open decision${n === 1 ? '' : 's'}</b>` +
    `<span class="ml-auto text-[10px] text-amber-200/60">★ = suggested, one click</span></button>` +
    `<div id="ny-body" class="px-2.5 pb-2.5 space-y-2${nyCollapsed ? ' hidden' : ''}">` +
    items.map(nyItemHtml).join('') + '</div></div>';
  // ny-toggle click handled by the delegated document listener
  el.querySelectorAll('.rq-in,.ask-in').forEach(i => {
    const k = i.dataset.id + '|' + (i.dataset.rq || 'ask');
    if (k in vals) {
      i.value = vals[k];
      if (focus === k) { i.focus(); i.setSelectionRange(i.value.length, i.value.length); }
    }
  });
}

// record a successful /respond: flag it so stale polls can't resurrect
// the row, update the in-memory copy, flash the band row, then drop it
function markAnswered(cid, rid, answer) {
  const key = cid + '|' + rid;
  pendingAns[key] = {answer, at: Date.now()};
  nyFlash[key] = true;
  const c = DATA && DATA.cards.find(x => x.id === cid);
  if (c) {
    if (rid === 'ask') {
      const a = askOf(c);
      if (a) { a.status = 'answered'; a.answer = answer; }
    } else {
      const r = (c.requests || []).find(x => String(x.id) === String(rid));
      if (r) { r.status = 'answered'; r.answer = answer; }
    }
  }
  toast('answer saved: ' + answer);
  renderBoard();
  setTimeout(() => { delete nyFlash[key]; renderNeedsYou(); }, 1600);
}

// cards.json regen lags a /respond write by up to a render tick — replay
// locally recorded answers onto stale reads; drop confirmed/expired keys
function healPending() {
  const t = Date.now();
  for (const [k, v] of Object.entries(pendingAns)) {
    const i = k.indexOf('|');
    const c = DATA.cards.find(x => x.id === k.slice(0, i));
    const rid = k.slice(i + 1);
    let confirmed = false;
    if (c) {
      if (rid === 'ask') {
        const a = askOf(c);
        if (a && a.status === 'answered') confirmed = true;
        else if (a) { a.status = 'answered'; a.answer = v.answer; }
      } else {
        const r = (c.requests || []).find(x => String(x.id) === rid);
        if (r && r.status === 'answered') confirmed = true;
        else if (r) { r.status = 'answered'; r.answer = v.answer; }
      }
    }
    if (confirmed || t - v.at > 10 * 60e3) delete pendingAns[k];
  }
}

// ---- card cycle control pane (read-only, KNB-0229 design) ----
// The pane lists cards with an active cycle (doing/review + queued/running
// action) and, when expanded, the 9 design sections mapped to sources:
// card record (DATA.cards), live board-api /cards rows (read-only GET),
// envelope/usage contracts are the design's evidence backends.
const cpLive = {};   // id -> live /apps/board-api/cards row (read-only)
const cpLiveAt = {}; // id -> fetch timestamp (TTL so polls don't loop)
const cpOpen = new Set(JSON.parse(localStorage.getItem('b2-cp-open') || '[]'));
const CP_MAX_TIMELINE = 5;
const CP_LIVE_TTL = 30000;

async function getApi(path) {
  try { const r = await fetch(API + path, {cache:'no-store'}); return await r.json(); }
  catch (e) { return {ok:false, error:String(e)}; }
}

function cpAct(c) { return (cpLive[c.id] && cpLive[c.id].action) || c.action || {}; }

function cpReason(c) {
  const a = cpAct(c);
  if (['done', 'archive'].includes(c.column)) return 'finished';
  const open = (c.requests || []).filter(r => !['answered', 'closed'].includes(r.status || ''));
  if (open.length) return 'open request ' + (open[0].id || '?');
  if (['claimed', 'running', 'queued', 'verifying', 'stalled'].includes(a.status || ''))
    return (a.status || '') + (a.target_host ? ' @ ' + a.target_host : '');
  if (c.awaiting_action) return 'awaiting action';
  return 'eligible';
}

function cpChip(v, cls) { return `<span class="cp-st ${cls}">${esc(v || '')}</span>`; }

function cpSection(t, rows) {
  return `<div class="cp-sec"><div class="cp-sec-t">${esc(t)}</div>` +
    `<div class="cp-rows">${rows.map(r =>
      `<div class="cp-rk">${esc(r.k)}</div><div class="cp-rv${r.muted ? ' muted' : ''}">` +
      (r.v ? esc(r.v) : '') +
      (r.hint ? `<div class="cp-hint">${esc(r.hint)}</div>` : '') +
      (r.rows ? r.rows : '') +
      (r.src ? `<div class="cp-src">from: ${esc(r.src)}</div>` : '') +
      `</div>`).join('')}</div></div>`;
}

const SRC_CARD = 'card record';
const SRC_LIVE = 'live action (board-api)';
const SRC_METRIC = 'DevNest lane metric (metrics.jsonl)';
const SRC_USAGE = 'runner usage.json (devin-dispatch/tasks)';
const cpEv = {};      // card id -> latest lane-metric rows (from /apps/board-api/jobs?card=)
const cpEvInf = new Set(); // card ids already fetched — evidence is host-local (read-once)

async function cpFetchEv(c) {
  const r = await getApi('/jobs?card=' + encodeURIComponent(c.id) + '&limit=5');
  cpEv[c.id] = Array.isArray(r && r.jobs) ? r.jobs : [];
  renderControl();
}

function cpTimeline(c) {
  const tl = (c.comms || []).slice(-CP_MAX_TIMELINE)
    .map(m => `<div class="cp-tl">${esc(m.at || '')} <b>${esc(m.from || '')}</b> — ${esc(m.text || '')}</div>`).join('');
  return tl || '<div class="cp-tl muted">no recent comms</div>';
}

function cpEscalate(c) {
  const ev = (cpEv[c.id] || [])[0] || {};
  const a = cpAct(c);
  const st = a.status || 'idle';
  const verified = a.verified === true;
  if (st === 'done' && verified)
    return {s: 'archive — verified done', conf: 'high',
            hint: 'action.verified — safe to age out', src: SRC_LIVE};
  if (st === 'failed' || (ev.verifier_pass === false && ev.failure_reason))
    return {s: 'review — dispatch failed', conf: 'high',
            hint: ev.failure_reason ||
              'review attempt result before re-arm (/action do=retry)',
            src: ev.failure_reason ? SRC_METRIC : SRC_LIVE};
  if (st === 'stalled')
    return {s: 'review — stalled (attempt cap)', conf: 'medium',
            hint: 'attempts at cap — Tony re-arms with /action do=retry',
            src: SRC_LIVE};
  if (st === 'queued')
    return {s: 'queue armed — awaiting executor', conf: 'medium',
            hint: 'dispatch rail order — watch target_host', src: SRC_LIVE};
  if (st === 'running' || st === 'verifying')
    return {s: 'review — in-flight, watch progress', conf: 'medium',
            hint: ev.verifier_pass !== undefined
              ? 'verifier_pass: ' + ev.verifier_pass
              : 'evidence: usage.json + lane_gate metrics',
            src: SRC_METRIC};
  if (c.column === 'review')
    return {s: 'review — review pass due', conf: 'medium',
            hint: 'review_kind: ' + esc(c.review_kind || ''), src: SRC_CARD};
  if (c.column === 'doing')
    return {s: 'none — cycle active in doing', conf: 'n/a', src: SRC_CARD};
  return {s: 'none — backlog/idle', conf: 'n/a', src: SRC_CARD};
}

function cpPane(c) {
  const a = cpAct(c);
  const open = (c.requests || []).filter(r => !['answered', 'closed'].includes(r.status || ''));
  const ev = (cpEv[c.id] || [])[0] || {};
  const u = ev.usage || {};
  const sections = [];
  // 1. Lifecycle & timeline
  sections.push(cpSection('Lifecycle & timeline', [
    {k: 'column', v: c.column || 'backlog', src: SRC_CARD},
    {k: 'updated', v: c.updated || '—', src: SRC_CARD},
    {k: 'comms (timeline)', v: '', rows: cpTimeline(c), src: SRC_CARD},
  ]));
  // 2. Eligibility & claim reason
  sections.push(cpSection('Eligibility & claim reason', [
    {k: 'status', v: cpChip(a.status || 'idle', 'cp-st-' + (a.status || 'idle')),
     src: a.status ? SRC_LIVE : SRC_CARD},
    {k: 'reason', v: cpReason(c),
     src: 'card-pick reasons (scripts/board/card-pick.py)'},
    {k: 'open requests', v: open.length ? open.map(r => r.id).join(', ') : 'none',
     src: SRC_CARD},
  ]));
  // 3. Executor / provider / model
  sections.push(cpSection('Executor / provider / model', [
    {k: 'executor', v: a.executor || '—', muted: !a.executor, src: a.executor ? SRC_LIVE : SRC_CARD},
    {k: 'lane', v: a.lane || '—', muted: !a.lane, src: a.lane ? SRC_LIVE : SRC_CARD},
    {k: 'model', v: a.model || '—', muted: !a.model, src: a.model ? SRC_LIVE : SRC_CARD},
    {k: 'provider', v: ev.provider || '—', muted: !ev.provider,
     src: ev.provider ? SRC_METRIC : undefined},
    {k: 'profile', v: a.agent_profile || a.profile || '—',
     muted: !(a.agent_profile || a.profile),
     src: (a.agent_profile || a.profile) ? SRC_LIVE : SRC_CARD},
  ]));
  // 4. Host / session
  sections.push(cpSection('Host / session', [
    {k: 'target host', v: a.target_host || '—', muted: !a.target_host, src: SRC_LIVE},
    {k: 'session', v: a.task_id || a.session || '—',
     hint: a.task_id ? 'task dir on host' : 'not linked — design gap', src: SRC_LIVE},
  ]));
  // 5. Queue & run duration — DevNest lane metric (§4)
  const dur = [];
  if (ev.queue_s !== undefined && ev.queue_s !== null)
    dur.push({k: 'queue wait', v: String(ev.queue_s) + 's', src: SRC_METRIC});
  if (ev.wall_s !== undefined && ev.wall_s !== null)
    dur.push({k: 'run duration', v: String(ev.wall_s) + 's', src: SRC_METRIC});
  if (!dur.length) dur.push({k: 'duration', v: 'no metric — design gap §4'});
  sections.push(cpSection('Queue & run duration', dur));
  // 6. Evidence: tokens & cost — lane metric + usage.json
  const inTok = ev.input_tokens !== undefined ? ev.input_tokens : u.input_tokens;
  const outTok = ev.output_tokens !== undefined ? ev.output_tokens : u.output_tokens;
  const costV = ev.provider_cost_usd !== undefined ? ev.provider_cost_usd : u.cost_usd;
  const tok = [];
  if (inTok !== undefined || outTok !== undefined)
    tok.push({k: 'tokens', v: `in ${inTok || 0} / out ${outTok || 0}`,
              src: ev.input_tokens !== undefined ? SRC_METRIC : SRC_USAGE});
  if (costV !== undefined)
    tok.push({k: 'provider cost', v: String(costV), src: SRC_METRIC});
  if (ev.combined_cost_usd !== undefined)
    tok.push({k: 'combined cost', v: String(ev.combined_cost_usd), src: SRC_METRIC});
  if (!tok.length) tok.push({k: 'tokens & cost', v: 'no evidence — design gap §4'});
  sections.push(cpSection('Evidence: tokens & cost', tok));
  // 7. Artifact & verifier
  sections.push(cpSection('Artifact & verifier', [
    {k: 'artifact', v: a.artifact || '—', muted: !a.artifact,
     src: a.artifact ? SRC_LIVE : SRC_CARD},
    {k: 'verified', v: a.verified === true ? 'true' : (a.verified === false ? 'false' : '—'), src: SRC_LIVE},
    {k: 'result', v: (a.result || '').slice(0, 220) || '—', src: a.result ? SRC_LIVE : undefined},
  ]));
  // 8. Attempts & failure
  const failSrc = ev.failure_reason ? SRC_METRIC : (a.result || a.failure ? SRC_LIVE : undefined);
  sections.push(cpSection('Attempts & failure', [
    {k: 'attempts', v: String(a.attempts || 0), src: SRC_LIVE},
    {k: 'failure', v: (ev.failure_reason || a.failure || a.result || '') || '—', src: failSrc},
  ]));
  // 9. Suggested escalation
  const es = cpEscalate(c);
  sections.push(cpSection('Suggested escalation', [
    {k: 'suggestion', v: es.s, src: es.src || SRC_CARD},
    {k: 'confidence', v: es.conf, src: es.src || SRC_CARD},
    {k: 'reason', v: es.hint || '', src: es.hint ? 'derived (action + lane metric)' : undefined},
  ]));
  return sections.join('');
}

function cpCards() {
  const out = [];
  for (const c of (DATA ? DATA.cards : [])) {
    const act = cpAct(c);
    const col = c.column || 'backlog';
    const active = col === 'doing' || col === 'review'
      || ['queued', 'running'].includes(act.status || '');
    if (active) out.push(c);
  }
  return out;
}

async function cpFetchLive(id) {
  const r = await getApi('/cards?id=' + encodeURIComponent(id) + '&limit=1');
  if (r && r.cards && r.cards[0]) {
    cpLive[id] = r.cards[0];
  }
  cpLiveAt[id] = Date.now();   // empty result: don't refetch on every poll
  renderControl();
}

function renderControl() {
  const el = document.getElementById('control');
  if (!el) return;
  const items = cpCards();
  if (!items.length) {
    el.innerHTML = '<div class="cp-head-small">Card cycle control — nothing Doing/Review, nothing queued.</div>';
    return;
  }
  if (!cpOpen.size) cpOpen.add(items[0].id);
  el.innerHTML = '<div class="cp-head-small">Card cycle control — read-only (v1)</div>' +
    items.map(c => {
      const act = cpAct(c);
      const open = (c.requests || []).filter(r => !['answered', 'closed'].includes(r.status || ''));
      const stCls = ['queued', 'running'].includes(act.status || '') ? 'cp-st-' + act.status
        : (['idle', 'done'].includes(act.status || '') ? 'cp-st-' + (act.status || 'idle') : 'cp-st-other');
      const h = `<div class="cp-card">` +
        `<button class="cp-head" data-id="${esc(c.id)}">` +
          `<span class="cp-caret">${cpOpen.has(c.id) ? '▾' : '▸'}</span>` +
          `<span class="cp-title">${esc((c.ref ? c.ref + ' ' : '') + (c.title || c.id))}</span>` +
          cpChip(act.status || 'idle', stCls) +
          (c.priority ? cpChip(c.priority, 'cp-st-other') : '') +
          (open.length ? cpChip(open.length + ' need you', 'cp-st-queued') : '') +
        `</button>` +
        (cpOpen.has(c.id) ? `<div class="cp-pane">${cpPane(c)}</div>` : '') +
        `</div>`;
      return h;
    }).join('');
  for (const id of [...cpOpen])
    if (!cpLiveAt[id] || Date.now() - cpLiveAt[id] > CP_LIVE_TTL) void cpFetchLive(id);
  // evidence: one /apps/board-api/jobs?card= fetch per card (read-only,
  // read-once per session — the pane shows what the ledger holds).
  for (const c of items) if (!cpEv[c.id] && !cpEvInf.has(c.id)) {
    cpEvInf.add(c.id);
    void cpFetchEv(c);
  }
}

// all interactive controls — one delegated listener survives poll
// re-renders: per-element onclick handlers get orphaned when innerHTML
// swaps between wiring and the user's click (2026-10-22: dead col-head
// clicks, dead option buttons). Order matters: specific controls before
// the .card catch-all.
document.addEventListener('click', async (e) => {
  let el = e.target.closest('.rq-opt');
  if (el) {
    const r = await api('/respond', {id: el.dataset.id, request_id: el.dataset.rq, answer: el.dataset.val});
    if (r && r.ok === false) { toast(r.error || 'refused'); return; }
    markAnswered(el.dataset.id, el.dataset.rq, el.dataset.val);
    return;
  }
  el = e.target.closest('.rq-btn');
  if (el) {
    const inp = el.parentElement.querySelector('.rq-in');
    if (!inp || !inp.value.trim()) return;
    const r = await api('/respond', {id: el.dataset.id, request_id: el.dataset.rq, answer: inp.value.trim()});
    if (r && r.ok === false) { toast(r.error || 'refused'); return; }
    markAnswered(el.dataset.id, el.dataset.rq, inp.value.trim());
    return;
  }
  el = e.target.closest('.ask-opt');
  if (el) {
    const r = await api('/respond', {id: el.dataset.id, option: Number(el.dataset.opt)});
    if (r && r.ok === false) { toast(r.error || 'refused'); return; }
    markAnswered(el.dataset.id, 'ask', el.textContent.trim().replace(/^★ /, ''));
    return;
  }
  el = e.target.closest('.ask-btn');
  if (el) {
    const inp = el.parentElement.querySelector('.ask-in');
    if (!inp || !inp.value.trim()) return;
    const r = await api('/respond', {id: el.dataset.id, text: inp.value.trim()});
    if (r && r.ok === false) { toast(r.error || 'refused'); return; }
    markAnswered(el.dataset.id, 'ask', inp.value.trim());
    return;
  }
  el = e.target.closest('.ny-card');
  if (el) { openModal(el.dataset.id); return; }
  el = e.target.closest('#ny-toggle');
  if (el) {
    nyCollapsed = !nyCollapsed;
    try { localStorage.setItem('b2-ny-collapsed', nyCollapsed ? '1' : '0'); } catch (err) {}
    document.getElementById('ny-body').classList.toggle('hidden', nyCollapsed);
    document.getElementById('ny-caret').textContent = nyCollapsed ? '▸' : '▾';
    return;
  }
  el = e.target.closest('.auto-tog');
  if (el) {
    autoOpen[el.dataset.col] = !autoOpen[el.dataset.col];
    localStorage.setItem('b2-auto', JSON.stringify(autoOpen));
    renderBoard();
    return;
  }
  el = e.target.closest('.more-tog');
  if (el) {
    const mc = el.dataset.col;
    moreOpen.has(mc) ? moreOpen.delete(mc) : moreOpen.add(mc);
    localStorage.setItem('b2-more', JSON.stringify([...moreOpen]));
    renderBoard();
    return;
  }
  el = e.target.closest('.cp-head');
  if (el) {
    const id = el.dataset.id;
    if (cpOpen.has(id)) cpOpen.delete(id); else cpOpen.add(id);
    localStorage.setItem('b2-cp-open', JSON.stringify([...cpOpen]));
    void cpFetchLive(id);
    return;
  }
  el = e.target.closest('.card');
  if (el && el.dataset.id) openModal(el.dataset.id);
});
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Enter') return;
  const inp = e.target.closest && e.target.closest('.rq-in,.ask-in');
  if (!inp) return;
  const b = inp.parentElement.querySelector('.rq-btn,.ask-btn');
  if (b) b.click();
});

function field(label, v) {
  if (!v) return '';
  return `<div class="mt-3"><div class="text-[10px] uppercase tracking-wide text-slate-500 mb-1">${label}</div>` +
    `<div class="text-sm text-slate-200 whitespace-pre-wrap">${esc(v)}</div></div>`;
}

function detailHtml(c) {
  const a = c.action || {};
  let h = `<div class="flex items-start gap-3">
    <div class="flex-1"><div class="text-lg font-semibold">${esc(c.title)}</div>
    <div class="text-xs text-slate-500 mt-0.5">${c.ref?`<span class="text-sky-400 font-semibold">${esc(c.ref)}</span> · `:''}${esc(c.id)} · ${esc(c.column||'backlog')} ${c.priority?'· '+esc(c.priority):''}</div>
    <div class="mt-1 flex gap-1 flex-wrap">${badgeHtml(c, c.column || 'backlog')}</div></div>
    <div class="flex flex-col gap-1 items-end shrink-0">
      ${!['queued','running','done'].includes(a.status||'idle') && (a.type || !['doing','done','verified','review'].includes(c.column||'')) ? `<button class="act text-xs bg-sky-700 hover:bg-sky-600 rounded px-2.5 py-1" data-do="queue" title="queue for dispatch — repo defaults to chaba unless action.repo is set">▶ Start</button>`:''}
      ${c.column !== 'done' ? `<button class="act text-xs bg-emerald-800 hover:bg-emerald-700 rounded px-2.5 py-1" data-do="close">✓ close</button>`:''}
      <select class="mv text-xs bg-slate-800 border border-slate-700 rounded px-2 py-1">
        <option value="">move to…</option>
        ${(DATA.columns||[]).map(x=>`<option ${x.id===c.column?'selected':''}>${esc(x.id)}</option>`).join('')}
      </select>
    </div></div>`;
  if (c.brief) h += `<div class="mt-3 border-l-4 border-sky-400 bg-sky-900/25 rounded-r px-3 py-2">` +
    `<div class="text-[10px] uppercase tracking-wide text-sky-300/80 mb-0.5">In plain terms</div>` +
    `<div class="text-[15px] leading-snug text-sky-50 whitespace-pre-wrap">${esc(c.brief)}</div></div>`;
  if ((c.lab||{}).hypothesis) h += field('🧪 hypothesis', c.lab.hypothesis) + field('metric', c.lab.metric) + field('outcome', c.lab.outcome);
  h += field('note', c.note) + field('spec', c.spec) + field('verify', c.verify) + field('help', c.help);
  if (askOf(c)) h += askHtml(c);
  for (const r of (c.requests||[])) h += reqHtml(c, r);
  const atts = cardAttach(c);
  if (atts.length) {
    h += '<div class="mt-3"><div class="text-[10px] uppercase tracking-wide text-slate-500 mb-1">📎 Attachments</div>' +
      '<div class="flex flex-wrap gap-2">' + atts.map(thumbHtml).join('') + '</div></div>';
  }
  const log = (c.comms||[]).slice(-20);
  if (log.length) {
    h += '<div class="mt-4"><div class="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Comms</div>' +
      log.map(m => `<div class="text-xs border-l-2 border-slate-700 pl-2 py-1"><span class="text-slate-500">${esc(m.at||m.ts||'')} · ${esc(m.from||m.who||'')}</span><br>${esc(m.text||m.msg||'')}${attachHtml(m.text||m.msg||'')}</div>`).join('') + '</div>';
  }
  h += `<div class="flex gap-1.5 mt-4"><input id="cm" class="flex-1 bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-xs" placeholder="comment…">` +
       `<button id="cm-btn" class="text-xs bg-slate-700 hover:bg-slate-600 rounded px-3">Post</button></div>`;
  return h;
}

function renderModal() {
  const ov = document.getElementById('overlay');
  const c = DATA && DATA.cards.find(x => x.id === sel);
  if (!c) { ov.classList.remove('open'); return; }
  const body = document.getElementById('modal-body');
  // preserve the half-typed comment + scroll across poll re-renders
  const cmv = (document.getElementById('cm') || {}).value;
  const st = document.getElementById('modal').scrollTop;
  body.innerHTML = detailHtml(c);
  ov.classList.add('open');
  document.getElementById('modal').scrollTop = st;
  const cm = document.getElementById('cm');
  if (cmv) cm.value = cmv;

  body.querySelectorAll('.act').forEach(b => b.onclick = async () => {
    const r = await api('/action', {id: c.id, do: b.dataset.do});
    toast(r.ok === false ? (r.error || 'refused') : b.dataset.do + ' ok'); await load();
  });
  body.querySelector('.mv').onchange = async (e) => {
    if (!e.target.value || e.target.value === c.column) return;
    const r = await api('/action', {id: c.id, do: 'move', column: e.target.value});
    toast(r.ok === false ? (r.error || 'refused') : 'moved'); await load();
  };
  document.getElementById('cm-btn').onclick = async () => {
    if (!cm.value.trim()) return;
    await api('/comment', {id: c.id, from: 'tony', text: cm.value.trim()});
    toast('comment added'); await load();
  };
}

function openModal(id) {
  sel = id;
  history.replaceState(null,'','#card='+id);
  renderModal();
}
function closeModal() {
  sel = null;
  history.replaceState(null,'',location.pathname);
  document.getElementById('overlay').classList.remove('open');
}

async function api(path, body) {
  try {
    // 60s: writes serialize on the board-api flock which kanban-commit
    // holds across pull+push — 15s aborted mid-commit (broken pipe).
    const r = await fetch(API + path, {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body), signal: AbortSignal.timeout(60000)});
    return await r.json();
  } catch (e) { return {ok:false, error:String(e)}; }
}

function toast(msg) {
  const d = document.createElement('div');
  d.className = 'fixed bottom-8 right-3 bg-slate-800 border border-slate-600 rounded px-3 py-2 text-sm z-70';
  d.style.zIndex = 70;
  d.textContent = msg; document.body.appendChild(d);
  setTimeout(() => d.remove(), 2500);
}

// zoom: −/+ cycle card density compact ↔ normal ↔ full via #board class
function applyDensity() {
  const b = document.getElementById('board');
  b.classList.remove('d-compact', 'd-normal', 'd-full');
  b.classList.add('d-' + density);
  document.getElementById('density-lbl').textContent = density;
  localStorage.setItem('b2-density', density);
}
function zoom(dir) {
  const i = DENSITIES.indexOf(density);
  density = DENSITIES[(i + dir + DENSITIES.length) % DENSITIES.length];
  applyDensity();
}
document.getElementById('z-out').onclick = () => zoom(-1);
document.getElementById('z-in').onclick = () => zoom(1);

// columns menu: toggle the dropdown; checkboxes flip hiddenCols and rerender
const colMenu = document.getElementById('colmenu');
document.getElementById('cols-btn').onclick = (e) => {
  e.stopPropagation();
  renderColMenu();
  colMenu.classList.toggle('open');
};
document.addEventListener('click', (e) => {
  if (!colMenu.contains(e.target)) colMenu.classList.remove('open');
});
colMenu.addEventListener('change', (e) => {
  const id = e.target.dataset.col;
  if (!id) return;
  if (e.target.checked) {
    hiddenCols.delete(id);
  } else if (COLS.length - hiddenCols.size > 1) {
    hiddenCols.add(id);
  } else {
    e.target.checked = true;  // keep ≥1 column visible
    return;
  }
  saveCols();
  renderBoard();
});

document.getElementById('q').oninput = (e) => {
  q = e.target.value;
  localStorage.setItem('b2-q', q);
  renderBoard();
};
document.getElementById('ny-pill').onclick = () => {
  nyCollapsed = false;
  renderNeedsYou();
  document.getElementById('needs-you').scrollIntoView({behavior:'smooth', block:'start'});
};
document.getElementById('modal-x').onclick = closeModal;
document.getElementById('overlay').onclick = e => { if (e.target.id === 'overlay') closeModal(); };
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && document.getElementById('overlay').classList.contains('open')) closeModal();
});
// ?decisions=1 deep-link (report/notifier surfaces) — open the band once
let decisionsLink = new URLSearchParams(location.search).has('decisions');

// 底部事件流：取全卡 comms 最近 30 条滚动展示；内容不变时不动 DOM，
// 让 -50% 无缝循环动画持续跑
function renderTicker() {
  const items = [];
  for (const c of (DATA ? DATA.cards : [])) for (const m of (c.comms || [])) {
    items.push({at: m.at || m.ts || '', id: c.id, from: m.from || m.who || '', text: m.text || m.msg || ''});
  }
  items.sort((a, b) => String(b.at).localeCompare(String(a.at)));
  const top = items.slice(0, 30);
  const track = document.getElementById('tk-track');
  if (!track) return;
  let html;
  if (!top.length) {
    html = '<span class="tk-item" style="opacity:.5">— no events —</span>';
  } else {
    html = top.map(it =>
      `<span class="tk-item"><b>${esc(it.at)}</b> ${esc(it.id)} · ${esc(it.from)} · ${esc(it.text)}</span><span class="tk-sep">◆</span>`).join('');
  }
  if (track.dataset.sig === html) return;
  track.dataset.sig = html;
  track.innerHTML = top.length ? html + html : html;
  track.style.animationDuration = Math.max(120, top.length * 10) + 's';
}

async function load() {
  try {
    const r = await fetch('cards.json?t=' + Date.now(), {cache:'no-store'});
    const prevCols = {};
    if (DATA) for (const pc of DATA.cards) prevCols[pc.id] = pc.column || 'backlog';
    const j = await r.json();
    if (DATA && DATA.page_version && j.page_version &&
        j.page_version !== DATA.page_version) {
      // page build changed upstream — reload once to pick up new code
      location.reload(); return;
    }
    for (const k in movedIn) delete movedIn[k];
    if (Object.keys(prevCols).length) for (const c of j.cards || []) {
      const nc = c.column || 'backlog';
      if (!(c.id in prevCols) || prevCols[c.id] !== nc) movedIn[c.id] = nc;
    }
    DATA = j;
    healPending();
    document.getElementById('gen').textContent = 'v' + (DATA.page_version||'') + ' · ' + (DATA.generated||'');
    const cm = location.hash.match(/card=([\w-]+)/); if (cm) sel = cm[1];
    renderBoard(); renderControl(); renderTicker();
    const dot = document.getElementById('live-dot');
    dot.className = 'w-2 h-2 rounded-full bg-emerald-400';
    dot.classList.remove('tick'); void dot.offsetWidth; dot.classList.add('tick');
    if (decisionsLink) {
      decisionsLink = false; nyCollapsed = false;
      renderNeedsYou();
      document.getElementById('needs-you').scrollIntoView({block:'start'});
    }
  } catch (e) { document.getElementById('live-dot').className = 'w-2 h-2 rounded-full bg-red-500'; }
}
applyDensity();
load(); setInterval(load, POLL);
// background tabs throttle setInterval hard (up to ~1/hr) — re-check
// the build version on focus so a stale page self-heals instead of
// needing a manual refresh
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) load();
});
</script>
</body>
</html>
"""


ARCHIVE_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Card Archive</title>
<style>
  body{background:#0b1220;color:#e2e8f0;font:13px/1.45 system-ui,sans-serif;margin:0}
  nav{background:#111a2e;border-bottom:1px solid #334155;padding:10px 16px;
      display:flex;gap:12px;align-items:center;position:sticky;top:0}
  a{color:#38bdf8;text-decoration:none} input{background:#0f172a;
      border:1px solid #334155;border-radius:6px;color:#e2e8f0;
      padding:5px 9px;font-size:13px}
  #list{max-width:1100px;margin:14px auto;padding:0 16px}
  .row{border-bottom:1px solid #1e293b;padding:7px 4px;cursor:pointer}
  .row:hover{background:#111a2e} .ref{color:#38bdf8;font-weight:600;
      margin-right:8px} .id{color:#64748b;font-size:11px;margin-right:8px}
  .meta{color:#64748b;font-size:11px} .title{color:#cbd5e1}
  #count{color:#64748b;font-size:12px}
</style></head><body>
<nav><a href="index.html">&larr; Board</a><b>Card Archive</b>
<span id="count"></span>
<input id="q" type="search" placeholder="Filter archived cards\u2026" style="margin-left:auto;width:260px">
</nav>
<div id="list"></div>
<script>
let DATA = null, q = '';
const esc = s => { const d=document.createElement('div');
  d.textContent=String(s??''); return d.innerHTML; };
async function load() {
  const r = await fetch('archive.json?t=' + Date.now(), {cache:'no-store'});
  DATA = await r.json();
  document.getElementById('count').textContent =
    DATA.cards.length + ' cards \u00b7 generated ' + (DATA.generated||'');
  render();
}
function render() {
  const ql = q.toLowerCase();
  const hit = (DATA.cards||[]).filter(c => !ql ||
    ((c.title||'')+' '+c.id+' '+(c.ref||'')+' '+(c.brief||'')).toLowerCase().includes(ql));
  document.getElementById('list').innerHTML = hit.map(c =>
    `<div class="row" data-id="${esc(c.id)}"><span class="ref">${esc(c.ref||'')}</span>` +
    `<span class="id">${esc(c.id)}</span><span class="title">${esc(c.title||'')}</span>` +
    `<div class="meta">${esc(c.column||'')} \u00b7 updated ${esc(c.updated||'')}</div></div>`
  ).join('') || '<div style="color:#64748b;padding:20px">no matches</div>';
}
document.getElementById('q').addEventListener('input', e => { q = e.target.value; render(); });
document.getElementById('list').addEventListener('click', e => {
  const r = e.target.closest('.row'); if (r) location.href = 'index.html#' + r.dataset.id;
});
load();
</script></body></html>
"""


def _tree_sig(d: Path) -> str:
    """Cheap tree signature (names + size + mtime, no content reads) —
    attachments can be multi-MB binaries, so a dir_hash-style content
    hash would tax every --if-changed tick. A git pull lands new mtimes,
    so pulled attachments still trigger the rerender+mirror."""
    h = hashlib.sha256()
    if d.is_dir():
        for p in sorted(d.rglob("*")):
            if not p.is_file():
                continue
            st = p.stat()
            h.update(f"{p.relative_to(d)}:{st.st_size}:{st.st_mtime_ns};"
                     .encode())
    return h.hexdigest()


def _mirror_attachments(src: Path, dst: Path) -> int:
    """Mirror the canonical attachment tree into the board app dir.
    Uploads are write-once (name collisions suffix, never rewrite), so a
    size match means the mirror is current."""
    if not src.is_dir():
        return 0
    n = 0
    for f in src.rglob("*"):
        if not f.is_file():
            continue
        d = dst / f.relative_to(src)
        if d.exists() and d.stat().st_size == f.stat().st_size:
            continue
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, d)
        n += 1
    return n


def main():
    man = yaml.load(MANIFEST.read_text(), Loader=_rb._YAML_LOADER)
    card_dir = REPO / man["card_dir"]
    out_path = REPO / "stacks/web/public/apps/board2/index.html"

    state_hash = None
    if "--if-changed" in sys.argv:
        state_hash = (_rb.dir_hash(card_dir)
                      + _rb.dir_hash(card_dir / "archive")
                      + _tree_sig(ATTACH_SRC))
        if STATE.exists() and STATE.read_text().strip() == state_hash \
                and out_path.exists():
            return 0
        # STATE advances only after the render lands (see render-board.py
        # — a crashed render must not poison the skip-set, OPS-1107).

    cards = _rb.load_cards(man)
    # mirror attachments FIRST so a card comms link never renders a
    # thumbnail whose file isn't servable yet
    n_att = _mirror_attachments(ATTACH_SRC, out_path.parent / "attachments")
    # archived cards (cards/archive/*.yml) get their own payload + page —
    # off the main board, still browsable (KNB-1178)
    archive_cards = []
    adir = card_dir / "archive"
    if adir.is_dir():
        for p in sorted(adir.glob("*.yml")):
            archive_cards.append(_rb._load_card_file(p))
    # persist the parse cache BEFORE compute_checks stamps 'checks' on
    # the card dicts — the cache must hold pristine parses only
    _rb._flush_cards_cache()
    archive_cards.sort(
        key=lambda c: str(c.get("updated") or ""), reverse=True)
    rank = {"high": 0, "medium": 1, "low": 3}
    cards.sort(key=lambda c: rank.get(str(c.get("priority") or "").lower(), 2))
    runs_by_slug = _rb._run_branches()
    outcomes = _rb._outcome_index()
    for c in cards:
        checks = _rb.compute_checks(c, runs_by_slug, outcomes)
        if checks:
            c["checks"] = checks
    _rules = man.get("rules")
    limit = (_rules if isinstance(_rules, dict) else {}) \
        .get("doing_limit", 2)

    ts = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M")

    page = PAGE.replace("__POLL_SECONDS__", str(POLL_SECONDS))

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
    out_path.with_name("archive.json").write_text(json.dumps(
        {"generated": ts, "cards": archive_cards},
        ensure_ascii=False, default=str))
    out_path.with_name("archive.html").write_text(ARCHIVE_PAGE)
    out_path.write_text(page)
    if state_hash is not None:
        STATE.write_text(state_hash + "\n")
    _rb._flush_mcache()
    print(f"wrote {out_path} + cards.json ({len(cards)} cards, v{ver}"
          + (f", {n_att} attachments mirrored" if n_att else "") + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
