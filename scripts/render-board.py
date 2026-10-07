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
import re
import subprocess
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


# --- verification checklist ---------------------------------------------
# Computed at render time against git + filesystem reality, so a card's
# chips reflect the repo — not hand-set flags that can lie (2026-10-06:
# vms-native-composite said merge_pending while run 3 was already deployed).

_TRUST_PY = re.compile(
    r"verif|auto-merged|merged into|confirm|works|lgtm|tested|checks out|"
    r"(?<!not )pushed\b[^\n]{0,60}\b[0-9a-f]*[a-f][0-9a-f]{6,39}\b", re.I)
_DEPLOY_PY = re.compile(r"\bdeploy", re.I)
_TASK_TS = re.compile(r"^(\d{8}-\d{6})-")


def _git(*args: str):
    try:
        p = subprocess.run(["git", "-C", str(REPO), *args],
                           capture_output=True, text=True, timeout=15)
        return p.returncode, p.stdout.strip()
    except Exception:
        return 1, ""


def _run_branches() -> dict:
    """dispatch/* branch names grouped by task slug (one card -> many runs)."""
    out = {}
    rc, txt = _git("branch", "--format=%(refname:short)", "--list",
                   "dispatch/*")
    if rc:
        return out
    for br in txt.splitlines():
        slug = _TASK_TS.sub("", br[len("dispatch/"):])
        out.setdefault(slug, []).append(br)
    for lst in out.values():
        lst.sort()  # timestamps sort lexically — last is newest
    return out


def _branch_merged(br: str) -> bool:
    """True if br's work is on origin/master — by ancestry, or by patch
    (a plain `git rebase` linearizes merge commits, so ancestry alone
    lies after an autostash rebase; git cherry catches that)."""
    if _git("merge-base", "--is-ancestor", br, "origin/master")[0] == 0:
        return True
    rc, out = _git("cherry", "origin/master", br)
    return rc == 0 and not any(l.startswith("+") for l in out.splitlines())


def _outcome_index() -> dict:
    """dispatch-outcome-*.md files, stem -> path. Scoped to docs/ssot/jobs
    in the repo and each dispatch worktree — a full-tree rglob per card
    made renders take ~17s."""
    idx = {}
    roots = [REPO / "docs/ssot/jobs"]
    roots += [wt / "docs/ssot/jobs" for wt in REPO.parent.glob("dispatch-wt-*")]
    for root in roots:
        if not root.is_dir():
            continue
        for f in root.rglob("dispatch-outcome-*.md"):
            idx.setdefault(f.stem, f)
    return idx


def _outcome_file(idx: dict, task_id: str):
    pref = f"dispatch-outcome-{task_id}"
    for stem, f in idx.items():
        if stem == pref or stem.startswith(pref):
            try:
                return str(f.relative_to(REPO))
            except ValueError:
                return str(f)
    return None


def _outcome_file_slug(idx: dict, slug: str):
    """Fallback: match the task slug inside the filename — catches the case
    where a card's task_id is an older run but a later run wrote the
    outcome (vms-native-composite: task_id=111612, outcome=211751)."""
    if not slug:
        return None
    for stem, f in idx.items():
        if slug in stem:
            try:
                return str(f.relative_to(REPO))
            except ValueError:
                return str(f)
    return None


def compute_checks(c: dict, runs_by_slug: dict, outcomes: dict) -> list:
    """Per-card verification chips; only for cards that had a dispatch run."""
    a = c.get("action") or {}
    tid = str(a.get("task_id") or "")
    slug = _TASK_TS.sub("", tid) if tid else ""
    runs = runs_by_slug.get(slug, []) if slug else []
    if not runs and a.get("status") not in ("done", "failed", "error"):
        return []
    checks = []

    # multi-run visibility — the blind spot that hid vms run 3
    if len(runs) > 1:
        checks.append({"k": f"{len(runs)} runs", "ok": None,
                       "how": "dispatch branches: " + ", ".join(runs)})

    # code merged — newest run branch vs origin/master; fall back to flag
    if runs:
        newest = runs[-1]
        if _branch_merged(newest):
            checks.append({"k": "code", "ok": True,
                           "how": f"{newest} on origin/master (ancestry or patch-equiv)"})
        else:
            merged = [b for b in runs if _branch_merged(b)]
            checks.append({"k": "code", "ok": False,
                           "how": f"{newest} NOT merged" +
                                  (f" (merged: {', '.join(merged)})"
                                   if merged else "")})
    elif "merge_pending" in a:
        checks.append({"k": "code", "ok": not a.get("merge_pending"),
                       "how": "merge_pending flag (no local branch found)"})

    # outcome artifact — any run's file counts
    tids = [tid] if tid else []
    tids += [b[len("dispatch/"):] for b in runs
             if b[len("dispatch/"):] != tid]
    found = next((p for t in tids if (p := _outcome_file(outcomes, t))),
                 None) or _outcome_file_slug(outcomes, slug)
    if tid or runs:
        checks.append({"k": "outcome", "ok": found is not None,
                       "how": found or f"no dispatch-outcome-{slug or '?'}*.md"})

    # deploy + verify — comms heuristics (verify mirrors isVerified)
    comms = c.get("comms") or []
    dep = next((m.get("text", "") for m in comms
                if _DEPLOY_PY.search(m.get("text") or "")), None)
    checks.append({"k": "deploy",
                   "ok": True if dep else (None if not tid else False),
                   "how": ("comms: " + dep[:80]) if dep
                          else "no deploy mention in comms"})
    v = a.get("verified")
    if v is not None:
        checks.append({"k": "verify",
                       "ok": v is True or v == "true",
                       "how": f"action.verified={v} (merge-guard)"})
    else:
        hit = next((m.get("text", "") for m in comms
                    if _TRUST_PY.search(m.get("text") or "")), None)
        checks.append({"k": "verify", "ok": hit is not None,
                       "how": ("comms: " + hit[:80]) if hit
                              else "no verification entry in comms"})
    return checks


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
    # legibility: `priority` drives intra-column order — "next-up" is
    # readable without a separate queue column. Stable: same-priority
    # cards keep file order.
    rank = {"high": 0, "medium": 1, "low": 3}
    cards.sort(key=lambda c: rank.get(str(c.get("priority") or "").lower(), 2))
    runs_by_slug = _run_branches()
    outcomes = _outcome_index()
    for c in cards:
        checks = compute_checks(c, runs_by_slug, outcomes)
        if checks:
            c["checks"] = checks
    cols = man["columns"]
    limit = man.get("rules", {}).get("doing_limit", 2)
    doing_sessions = {}
    for c in cards:
        s = (c.get("claim") or {}).get("session")
        if c.get("column") == "doing" and s:
            doing_sessions[s] = doing_sessions.get(s, 0) + 1
    over = [s for s, n in doing_sessions.items() if n > limit]

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
    html {{ font-size: 18px; }}
    .bg-bg {{ background-color: #1a1a2e; }}
    .bg-card {{ background-color: #16213e; }}
    .bg-accent {{ background-color: #0a84ff; }}
    .board-cols {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }}
    .board-card.flash {{ border-color: #0a84ff !important; box-shadow: 0 0 0 2px rgba(10,132,255,.5); transition: border-color .2s, box-shadow .2s; }}
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
const POLL_SECONDS = {POLL_SECONDS};
const POLL_MS = POLL_SECONDS * 1000;
const BUILT = '@@VER@@';
let DATA = null;
let lang = 'en';
let filter_q = '';
let openCard = null;
let busy = false;
let nyCollapsed = false;
try {{ nyCollapsed = localStorage.getItem('board-ny-collapsed') === '1'; }} catch (e) {{}}

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

async function api(path, body, timeoutMs) {{
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), timeoutMs || 90000);
  try {{
    const r = await fetch(API + path, {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(body),
      signal: ac.signal,
    }});
    const j = await r.json().catch(() => ({{}}));
    if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
    return j;
  }} finally {{ clearTimeout(t); }}
}}

function actBtns(c, inModal) {{
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
  else if (a.type)
    h += `<button class="abtn text-xs bg-accent hover:opacity-90 text-white rounded px-2 py-0.5" data-id="${{esc(c.id)}}" data-do="queue">${{esc(a.button || '▶ Start')}}</button>`;
  else if (inModal)
    h += `<span class="text-xs text-slate-500">no action spec — add <code>action:</code> to the card to dispatch</span>`;
  return h;
}}

function reqAnswerHtml(c, r) {{
  const opts = r.options || [];
  if (opts.length) {{
    let h = '<div class="flex flex-wrap gap-1.5 mt-1">';
    let sugVal = '';
    for (const o of opts) {{
      const lbl = typeof o === 'string' ? o : (o.label || o.id);
      const val = typeof o === 'string' ? o : (o.id + ' — ' + (o.label || ''));
      const sug = r.suggested && (r.suggested === val || r.suggested === lbl ||
        (typeof o !== 'string' && r.suggested === o.id));
      if (sug) sugVal = val;
      h += `<button class="rq-opt text-xs ${{sug ? 'bg-emerald-800 hover:bg-emerald-700 text-emerald-100 ring-1 ring-emerald-400 font-semibold' : 'bg-amber-800/70 hover:bg-amber-700 text-amber-100'}} rounded px-2 py-1" data-id="${{esc(c.id)}}" data-rq="${{esc(r.id)}}" data-val="${{esc(val)}}">${{sug ? '★ ' : ''}}${{esc(lbl)}}</button>`;
    }}
    if (r.suggested)
      h += `<button class="rq-opt text-xs bg-emerald-700 hover:bg-emerald-600 text-white font-semibold rounded px-2 py-1" title="accept the suggested option" data-id="${{esc(c.id)}}" data-rq="${{esc(r.id)}}" data-val="${{esc(sugVal || r.suggested)}}">✓ accept suggestion</button>`;
    return h + '</div>';
  }}
  return `<div class="flex gap-1 mt-1"><input class="rq-in flex-1 bg-slate-900 border border-slate-700 rounded px-1.5 py-1 text-xs" data-id="${{esc(c.id)}}" data-rq="${{esc(r.id)}}" placeholder="your answer…">` +
         `<button class="rq-btn text-xs bg-slate-700 hover:bg-slate-600 rounded px-2" data-id="${{esc(c.id)}}" data-rq="${{esc(r.id)}}">Answer</button></div>`;
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
      if (inModal) h += reqAnswerHtml(c, r);
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
  const PRIO = {{high: ['bg-red-900/70 text-red-200', '▲ high'],
               medium: ['bg-sky-900/60 text-sky-200', '● medium'],
               low: ['bg-slate-700/60 text-slate-400', '▽ low']}};
  const pv = PRIO[String(c.priority || '').toLowerCase()];
  if (pv) badges += `<span class="text-xs ${{pv[0]}} rounded px-1.5 py-0.5">${{pv[1]}}</span> `;
  const lab = c.lab || {{}};
  if (lab.review_by) {{
    const overdue = !lab.outcome && lab.review_by < new Date().toISOString().slice(0,10);
    badges += `<span class="text-xs ${{overdue ? 'bg-red-800/80 text-red-100' : 'bg-violet-800/70 text-violet-100'}} rounded px-1.5 py-0.5">🧪 review ${{esc(lab.review_by)}}${{overdue ? ' ⚠' : ''}}</span> `;
  }}
  if (lab.outcome)
    badges += `<span class="text-xs bg-violet-900/60 text-violet-200 rounded px-1.5 py-0.5">🧪 ${{esc(lab.outcome)}}</span> `;
  const a = c.action || {{}};
  const st = a.status || 'idle';
  if (st === 'queued') badges += '<span class="text-xs bg-amber-800/70 text-amber-200 rounded px-1.5 py-0.5">⏳ queued</span> ';
  else if (st === 'running') badges += '<span class="text-xs bg-sky-700/80 text-sky-100 rounded px-1.5 py-0.5">⚙ running</span> ';
  else if (st === 'failed') badges += '<span class="text-xs bg-red-800/70 text-red-100 rounded px-1.5 py-0.5">✖ failed</span> ';
  if ((c.column || 'backlog') === 'review') {{
    const v = isVerified(c);
    badges += v.ok
      ? `<span class="text-xs bg-emerald-800/80 text-emerald-100 rounded px-1.5 py-0.5" title="${{esc(v.how)}}">✔ verified</span> `
      : `<span class="text-xs bg-amber-900/80 text-amber-200 rounded px-1.5 py-0.5" title="${{esc(v.how)}}">⚠ claimed</span> `;
  }}
  // verification checklist — computed server-side against git/fs reality
  for (const k of (c.checks || [])) {{
    const cls = k.ok === true ? 'bg-emerald-900/70 text-emerald-200'
              : k.ok === false ? 'bg-red-900/70 text-red-200'
              : 'bg-slate-700/60 text-slate-400';
    const mark = k.ok === true ? '✓' : k.ok === false ? '✗' : '·';
    badges += `<span class="text-xs ${{cls}} rounded px-1.5 py-0.5" title="${{esc(k.how || '')}}">${{mark}} ${{esc(k.k)}}</span> `;
  }}

  return `<div class="board-card bg-card border border-slate-700 rounded-lg p-3 mb-2 cursor-pointer hover:border-slate-500" data-id="${{esc(c.id)}}" data-text="${{esc(((c.title||'')+' '+c.id).toLowerCase())}}">` +
    `<div class="font-medium text-sm">${{esc(c.title || c.id)}}</div>` +
    (badges ? `<div class="mt-1.5 flex flex-wrap gap-1">${{badges}}</div>` : '') +
    `<div class="text-xs text-slate-400 mt-1.5">${{esc(c.note || '')}}</div>` +
    `<div class="text-[10px] text-slate-500 mt-1">${{esc(c.id)}} · ${{esc(c.updated || '')}}</div>` +
    '</div>';
}}

// 'verified' signals incl. the auto-merge comm — note: bare /merged/
// would match "unmerged commits remain", so require 'merged into'|'auto-merged';
// the pushed-SHA arm requires >=1 hex letter so timestamps like 20261005
// don't count, and lookbehinds keep "not pushed"/"n't pushed" negative
const TRUST_RE = /verif|auto-merged|merged into|confirm|works|lgtm|tested|checks out|(?<!not )(?<!n't )pushed\\b[^.\\n]{{0,60}}\\b(?=[0-9a-f]*[a-f])[0-9a-f]{{7,40}}\\b/i;
// Verified-vs-claimed: an explicit action.verified (bool — dispatch-merge-guard
// writes it once real merge/push checks land) wins over the comms heuristic,
// including an explicit false (guard checked and the work is NOT verified).
function isVerified(c) {{
  const v = (c.action || {{}}).verified;
  if (v !== undefined && v !== null)
    return {{ok: v === true || v === 'true',
             how: 'action.verified=' + v + ' (merge-guard)'}};
  const hit = (c.comms || []).find(m => TRUST_RE.test(m.text || ''));
  return {{ok: !!hit,
           how: hit ? 'comms heuristic: ' + String(hit.text).slice(0, 80)
                    : 'no verification entry in comms'}};
}}
// automation-generated card ids — collapsed under per-column groups
const AUTO_RE = /^(cms|logs|gev|vcast|disk)-auto-|-auto-health$/;
let autoOpen = {{}};
try {{ autoOpen = JSON.parse(localStorage.getItem('board-auto-open') || '{{}}'); }} catch (e) {{}}
const REVIEW_RE = /(?:->|→|—|–)\\s*review\\b/i;

function tsOf(s) {{
  const m = String(s || '').match(/^(\\d{{4}}-\\d{{2}}-\\d{{2}})(?:[ T](\\d{{2}}:\\d{{2}}))?/);
  return m ? Date.parse(m[1] + 'T' + (m[2] || '00:00') + ':00+07:00') : NaN;
}}

function reviewSince(c) {{
  let t = tsOf(c.updated);
  for (const m of c.comms || [])
    if (REVIEW_RE.test(m.text || '')) {{ const d = tsOf(m.at); if (!isNaN(d)) t = d; }}
  if (isNaN(t))
    for (const m of c.comms || []) {{ const d = tsOf(m.at); if (!isNaN(d) && (isNaN(t) || d > t)) t = d; }}
  return t;
}}

function needsYou() {{
  const items = [];
  for (const c of DATA.cards) {{
    for (const r of c.requests || [])
      if (r.status !== 'answered') items.push({{kind: 'request', c, r}});
    if ((c.column || 'backlog') === 'review') {{
      const verified = isVerified(c).ok;
      const t = reviewSince(c);
      if (!verified && !isNaN(t) && Date.now() - t > 24 * 3600e3)
        items.push({{kind: 'stale-review', c, ageH: Math.round((Date.now() - t) / 3600e3)}});
    }}
    if ((c.column || 'backlog') === 'doing') {{
      const cs = tsOf((c.claim || {{}}).since);
      if (!isNaN(cs) && Date.now() - cs > 72 * 3600e3)
        items.push({{kind: 'stale-claim', c, ageH: Math.round((Date.now() - cs) / 3600e3)}});
    }}
    const st = (c.action || {{}}).status;
    if (st === 'failed' || st === 'error') items.push({{kind: 'failed', c}});
    if (c.awaiting_action && (c.column || 'backlog') !== 'done')
      items.push({{kind: 'answered', c}});
  }}
  return items;
}}

function nyItemHtml(it) {{
  const c = it.c;
  const head = `<button class="ny-btn text-xs font-medium text-sky-300 hover:text-sky-200" data-id="${{esc(c.id)}}">${{esc(c.title || c.id)}}</button>` +
    `<span class="text-[10px] text-slate-500">${{esc(c.id)}}</span>`;
  if (it.kind === 'request')
    return `<div class="border border-amber-700/40 rounded p-2 bg-amber-950/30"><div class="flex items-baseline gap-2 flex-wrap">${{head}}</div>` +
      `<div class="text-xs text-amber-200 mt-1">❓ ${{esc(it.r.ask)}}</div>${{reqAnswerHtml(c, it.r)}}</div>`;
  if (it.kind === 'stale-review')
    return `<div class="border border-violet-700/40 rounded p-2 bg-violet-950/20"><div class="flex items-center gap-2 flex-wrap">${{head}}` +
      `<span class="text-xs text-violet-200">in review ${{it.ageH}}h — no verification entry</span>` +
      `<button class="ny-verify text-xs bg-emerald-800 hover:bg-emerald-700 text-white rounded px-2 py-0.5" data-id="${{esc(c.id)}}">✔ verify</button></div></div>`;
  if (it.kind === 'stale-claim')
    return `<div class="border border-slate-600/60 rounded p-2 bg-slate-800/40"><div class="flex items-center gap-2 flex-wrap">${{head}}` +
      `<span class="text-xs text-slate-300">claim ${{it.ageH}}h old — reclaimable per doing SLA</span></div></div>`;
  if (it.kind === 'answered') {{
    const a = c.action || {{}};
    const queueBtn = a.type && a.status !== 'queued' && a.status !== 'running'
      ? `<button class="abtn text-xs bg-accent hover:opacity-90 text-white rounded px-2 py-0.5" data-id="${{esc(c.id)}}" data-do="queue">▶ queue it</button>`
      : `<span class="text-[10px] text-slate-500">no action armed — spec one or triage manually</span>`;
    return `<div class="border border-sky-700/40 rounded p-2 bg-sky-950/20"><div class="flex items-center gap-2 flex-wrap">${{head}}` +
      `<span class="text-xs text-sky-200">answer recorded — needs triage</span>${{queueBtn}}</div></div>`;
  }}
  const res = (c.action || {{}}).result;
  return `<div class="border border-red-700/40 rounded p-2 bg-red-950/20"><div class="flex items-center gap-2 flex-wrap">${{head}}` +
    `<span class="text-xs text-red-300">dispatch ${{esc((c.action || {{}}).status || 'failed')}}</span>` +
    `<button class="abtn text-xs bg-red-800 hover:bg-red-700 text-white rounded px-2 py-0.5" data-id="${{esc(c.id)}}" data-do="retry">↺ Retry</button></div>` +
    (res ? `<div class="text-xs text-slate-400 mt-1">${{esc(String(res).slice(0, 160))}}</div>` : '') + '</div>';
}}

function render() {{
  if (!DATA) return;
  const counts = {{}};
  for (const c of DATA.cards) counts[c.column || 'backlog'] = (counts[c.column || 'backlog'] || 0) + 1;

  let cols = '';
  for (const col of DATA.columns) {{
    const all = DATA.cards.filter(c => (c.column || 'backlog') === col.id);
    const norm = all.filter(c => !AUTO_RE.test(c.id));
    const autos = all.filter(c => AUTO_RE.test(c.id));
    let body;
    if (col.id === 'review') {{
      // review is three jobs in one column — group by review_kind so
      // decisions don't drown under verify-me dispatches and auto triage
      const grp = {{decide: [], verify: [], triage: []}};
      for (const c of norm) (grp[c.review_kind] || grp.verify).push(c);
      const grpHtml = (tag, list) => !list.length ? '' :
        `<div class="text-[10px] uppercase tracking-wide text-slate-500 mt-2 mb-1">${{tag}} (${{list.length}})</div>` +
        list.map(cardHtml).join('');
      body = grpHtml('❓ decide', grp.decide) + grpHtml('✔ verify', grp.verify) + grpHtml('🤖 triage', grp.triage);
    }} else {{
      body = norm.map(cardHtml).join('');
    }}
    if (autos.length) {{
      const open = !!autoOpen[col.id];
      body += `<div class="border border-slate-700/50 rounded p-2 mt-1 opacity-75">` +
        `<div class="auto-tog text-xs text-slate-500 cursor-pointer select-none" data-col="${{esc(col.id)}}">${{open ? '▾' : '▸'}} automation (${{autos.length}})</div>` +
        (open ? `<div class="mt-1.5">${{autos.map(cardHtml).join('')}}</div>` : '') +
        '</div>';
    }}
    if (!body) body = '<div class="text-slate-500 text-sm italic">—</div>';
    cols += `<div><div class="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">` +
      `<span class="col-title" data-en="${{esc(col.title)}}" data-th="${{esc(col.title)}}">${{esc(col.title)}}</span> · ${{counts[col.id] || 0}}</div>` +
      `<div class="bg-slate-800/40 border border-slate-700/60 rounded-lg p-2 min-h-[80px]">${{body}}</div></div>`;
  }}
  document.getElementById('board-cols').innerHTML = cols;

  // needs-you band
  const nyInVals = {{}};
  let nyFocus = null;
  document.querySelectorAll('#needs-you .rq-in').forEach(i => {{
    nyInVals[i.dataset.id + '|' + i.dataset.rq] = i.value;
    if (document.activeElement === i) nyFocus = i.dataset.id + '|' + i.dataset.rq;
  }});
  const nyItems = needsYou();
  const nyEl = document.getElementById('needs-you');
  if (!nyItems.length) {{
    nyEl.innerHTML = '';
  }} else {{
    const n = nyItems.length;
    nyEl.innerHTML =
      `<div class="bg-amber-900/40 border border-amber-600/60 rounded mb-3">` +
      `<button id="ny-toggle" class="w-full text-left px-2.5 py-2 text-amber-100 text-sm flex items-center gap-2">` +
      `<span id="ny-caret">${{nyCollapsed ? '▸' : '▾'}}</span>` +
      `<b>${{n}} thing${{n === 1 ? '' : 's'}} need${{n === 1 ? 's' : ''}} you</b></button>` +
      `<div id="ny-body" class="px-2.5 pb-2.5 space-y-2${{nyCollapsed ? ' hidden' : ''}}">` +
      nyItems.map(nyItemHtml).join('') + '</div></div>';
    document.getElementById('ny-toggle').onclick = () => {{
      nyCollapsed = !nyCollapsed;
      try {{ localStorage.setItem('board-ny-collapsed', nyCollapsed ? '1' : '0'); }} catch (e) {{}}
      document.getElementById('ny-body').classList.toggle('hidden', nyCollapsed);
      document.getElementById('ny-caret').textContent = nyCollapsed ? '▸' : '▾';
    }};
    document.querySelectorAll('#needs-you .rq-in').forEach(i => {{
      const k = i.dataset.id + '|' + i.dataset.rq;
      if (k in nyInVals) {{
        i.value = nyInVals[k];
        if (nyFocus === k) {{ i.focus(); i.setSelectionRange(i.value.length, i.value.length); }}
      }}
    }});
  }}

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
    `Rendered ${{DATA.generated}} — cards in docs/ssot/kanban/cards/ · live (polls ${{POLL_SECONDS}}s) · v${{BUILT}}`;

  wire();
  setLang(lang);
  applyFilter();
  // keep the open modal fresh — but don't wipe an in-progress comment
  const ae = document.activeElement;
  const typing = ae && (ae.classList.contains('cm-in') || ae.classList.contains('rq-in'));
  const prevCmt = document.getElementById('cm-comment');
  const cmtVal = prevCmt ? prevCmt.value : '';
  const rqVals = {{}};
  document.querySelectorAll('#card-modal .rq-in').forEach(i => {{ if (i.value) rqVals[i.dataset.rq] = i.value; }});
  if (openCard && !typing) {{
    showCard(openCard);
    if (cmtVal) {{ const i = document.getElementById('cm-comment'); if (i) i.value = cmtVal; }}
    for (const rq in rqVals) {{
      const i = document.querySelector(`#card-modal .rq-in[data-rq="${{CSS.escape(rq)}}"]`);
      if (i) i.value = rqVals[rq];
    }}
  }}
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
    `<div class="flex flex-wrap gap-1.5 mb-3">${{actBtns(c, true)}}${{c.help ? `<button id="cm-help" class="text-xs bg-slate-700 hover:bg-slate-600 rounded px-2 py-1">? help</button>` : ''}}</div>` +
    `<div class="flex flex-wrap gap-1.5 mb-4">${{colBtns}}</div>` +
    ((c.lab && (c.lab.hypothesis || c.lab.metric)) ? `<div class="mb-3 border-l-2 border-violet-600 pl-2"><div class="text-[10px] uppercase tracking-wide text-violet-400 mb-1">Lab</div>${{c.lab.hypothesis ? `<div class="text-xs text-slate-300">hypothesis: ${{esc(c.lab.hypothesis)}}</div>` : ''}}${{c.lab.metric ? `<div class="text-xs text-slate-400">metric: ${{esc(c.lab.metric)}}</div>` : ''}}</div>` : '') +
    (c.spec ? `<div class="mb-3"><div class="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Spec</div><pre class="text-xs text-slate-300 whitespace-pre-wrap font-sans border-l-2 border-slate-600 pl-2">${{esc(c.spec)}}</pre></div>` : '') +
    ((c.requests || []).length ? `<div class="mb-3"><div class="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Requests</div>${{reqList(c, true)}}</div>` : '') +
    ((c.comms || []).length ? `<div class="mb-3"><div class="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Comms</div>${{commsList(c)}}</div>` : '') +
    `<div class="flex gap-1.5 mt-4 border-t border-slate-700/60 pt-3">` +
      `<input id="cm-comment" class="cm-in flex-1 bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-xs" placeholder="comment on this card…">` +
      `<button id="cm-send" class="text-xs bg-slate-700 hover:bg-slate-600 rounded px-3">Send</button></div>`;

  document.getElementById('cm-close').onclick = () => {{ modal.classList.add('hidden'); openCard = null; }};
  modal.onclick = e => {{ if (e.target === modal) {{ modal.classList.add('hidden'); openCard = null; }} }};
  if (c.help) document.getElementById('cm-help').onclick = () => openHelp(c.title || c.id, c.help);
  document.getElementById('cm-send').onclick = async () => {{
    const inp = document.getElementById('cm-comment');
    if (!inp.value.trim()) {{ toast('type a comment first'); return; }}
    try {{ await api('/comment', {{id, from: 'tony', text: inp.value.trim()}}); toast('comment added'); await load(); }}
    catch (e) {{ toast('error: ' + e.message, true); }}
  }};
  document.getElementById('cm-comment').onkeydown = e => {{ if (e.key === 'Enter') document.getElementById('cm-send').click(); }};
  wire(); // modal buttons (.abtn/.mv-btn/.rq-*) are injected after render — bind them now
  modal.classList.remove('hidden');
}}

async function doAct(id, verb, extra) {{
  if (busy) {{ toast('still working on previous action…', true); return; }}
  busy = true;
  try {{
    const r = await api('/action', Object.assign({{id, do: verb}}, extra || {{}}));
    toast(r.message || 'ok', /^blocked/i.test(r.message || ''));
    await load();
  }} catch (e) {{
    toast('error: ' + (e.name === 'AbortError' ? 'request timed out — click again' : e.message), true);
  }}
  busy = false;
}}

function scrollToCard(id) {{
  const el = document.querySelector(`.board-card[data-id="${{CSS.escape(id)}}"]`);
  if (!el) return;
  el.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
  el.classList.add('flash');
  setTimeout(() => el.classList.remove('flash'), 1600);
}}

function wire() {{
  document.querySelectorAll('.board-card').forEach(el =>
    el.onclick = e => {{ if (!e.target.closest('button,input')) showCard(el.dataset.id); }});
  document.querySelectorAll('.side-card,.ny-btn').forEach(el =>
    el.onclick = e => {{ scrollToCard(el.dataset.id); showCard(el.dataset.id); }});
  document.querySelectorAll('.abtn').forEach(b =>
    b.onclick = e => {{ e.stopPropagation(); doAct(b.dataset.id, b.dataset.do); }});
  document.querySelectorAll('.mv-btn').forEach(b =>
    b.onclick = e => {{ e.stopPropagation(); doAct(openCard, 'move', {{column: b.dataset.col}}); }});
  document.querySelectorAll('.rq-btn').forEach(b =>
    b.onclick = async e => {{
      e.stopPropagation();
      const cid = b.dataset.id || openCard;
      const scope = b.closest('#needs-you') ? '#needs-you' : '#card-modal';
      const inp = [...document.querySelectorAll(scope + ' .rq-in')]
        .find(i => i.dataset.rq === b.dataset.rq && (i.dataset.id || openCard) === cid);
      if (!inp || !inp.value.trim()) return;
      try {{ await api('/respond', {{id: cid, request_id: b.dataset.rq, answer: inp.value.trim()}}); toast('answer saved'); await load(); }}
      catch (err) {{ toast('error: ' + err.message, true); }}
    }});
  document.querySelectorAll('.rq-in').forEach(inp =>
    inp.onkeydown = e => {{
      if (e.key !== 'Enter') return;
      e.stopPropagation();
      const scope = inp.closest('#needs-you') ? '#needs-you' : '#card-modal';
      const b = [...document.querySelectorAll(scope + ' .rq-btn')]
        .find(x => x.dataset.rq === inp.dataset.rq && x.dataset.id === inp.dataset.id);
      if (b) b.click();
    }});
  document.querySelectorAll('.rq-opt').forEach(b =>
    b.onclick = async e => {{
      e.stopPropagation();
      try {{ await api('/respond', {{id: b.dataset.id || openCard, request_id: b.dataset.rq, answer: b.dataset.val}}); toast('answer saved: ' + b.dataset.val); await load(); }}
      catch (err) {{ toast('error: ' + err.message, true); }}
    }});
  document.querySelectorAll('.ny-verify').forEach(b =>
    b.onclick = async e => {{
      e.stopPropagation();
      try {{ await api('/comment', {{id: b.dataset.id, from: 'tony', text: 'verified'}}); toast('marked verified'); await load(); }}
      catch (err) {{ toast('error: ' + err.message, true); }}
    }});
  document.querySelectorAll('.auto-tog').forEach(el =>
    el.onclick = e => {{
      e.stopPropagation();
      autoOpen[el.dataset.col] = !autoOpen[el.dataset.col];
      try {{ localStorage.setItem('board-auto-open', JSON.stringify(autoOpen)); }} catch (err) {{}}
      render();
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
    const r = await fetch('cards.json?t=' + Date.now(), {{cache: 'no-store'}});
    DATA = await r.json();
    if (DATA.page_version && DATA.page_version !== BUILT) {{
      toast('board updated — reloading');
      setTimeout(() => location.reload(), 900);
      return;
    }}
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

// Register the shared /apps/ service worker. Every load runs register(),
// which makes the browser check sw.js for updates — if an old caching
// worker is still installed this replaces it; controllerchange then
// reloads once so the fresh SW (pass-through + apps-* cache purge)
// takes over and the next document fetch comes from the network.
if ('serviceWorker' in navigator) {{
  navigator.serviceWorker.register('/apps/sw.js?v=7', {{scope: '/apps/'}}).catch(() => {{}});
  let swReloaded = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {{
    if (!swReloaded) {{ swReloaded = true; location.reload(); }}
  }});
}}

load();
setInterval(load, POLL_MS);
</script>
</body>
</html>
"""
    # Self-updating page: version = hash of the rendered html with the
    # placeholder stripped, so it only changes when the template/JS changes
    # (re-rendering identical code yields the same version — no reload loop).
    ver = hashlib.sha256(page.replace("@@VER@@", "").encode()).hexdigest()[:12]
    page = page.replace("@@VER@@", ver)

    payload = {
        "generated": ts,
        "page_version": ver,
        "columns": cols,
        "doing_limit": limit,
        "over_limit": over,
        "cards": cards,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    json_path = out_path.with_name("cards.json")
    json_path.write_text(json.dumps(payload, ensure_ascii=False,
                                    default=str))  # yaml scalars -> date/datetime

    out_path.write_text(page)
    print(f"wrote {out_path} + cards.json ({len(cards)} cards, v{ver})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
