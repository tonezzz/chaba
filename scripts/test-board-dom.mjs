#!/usr/bin/env node
// DOM-stub harness for the generated board page.
// Runs the inline <script> from stacks/web/public/apps/board/index.html
// against a minimal fake DOM + localStorage + fetch(cards.json), then
// exercises the automation-group behaviour:
//   1. auto cards grouped under per-column "automation (N)" headers,
//      collapsed by default; human cards always rendered
//   2. .auto-tog click expands + persists to localStorage('board-auto-open')
//   3. persisted state survives a fresh boot
//   4. sidebar click on a collapsed auto card auto-expands + scrolls
//   5. text filter reveals collapsed groups containing a match
//
// Usage: node scripts/test-board-dom.mjs [path-to-index.html]
// Requires cards.json next to index.html (run scripts/render-board.py first).
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const HTML_PATH = process.argv[2] ||
  new URL('../stacks/web/public/apps/board/index.html', import.meta.url).pathname;
const JSON_PATH = join(dirname(HTML_PATH), 'cards.json');

const htmlSrc = readFileSync(HTML_PATH, 'utf8');
const payload = JSON.parse(readFileSync(JSON_PATH, 'utf8'));

// ---- tiny HTML parser -> stub element tree -------------------------------
const VOID = new Set(['input', 'br', 'img', 'hr', 'meta', 'link', 'area', 'source']);

function camel(s) { return s.replace(/-([a-z])/g, (_, c) => c.toUpperCase()); }

class ClassList {
  constructor(el) { this.el = el; this.set = new Set(); }
  _sync() { this.el.attrs.class = [...this.set].join(' '); }
  from(str) { this.set = new Set(String(str || '').split(/\s+/).filter(Boolean)); }
  add(...c) { c.forEach(x => this.set.add(x)); this._sync(); }
  remove(...c) { c.forEach(x => this.set.delete(x)); this._sync(); }
  toggle(c, force) {
    const on = force === undefined ? !this.set.has(c) : !!force;
    on ? this.set.add(c) : this.set.delete(c); this._sync(); return on;
  }
  contains(c) { return this.set.has(c); }
}

class El {
  constructor(tag, doc) {
    this.tagName = tag.toUpperCase();
    this.doc = doc;
    this.attrs = {};
    this.dataset = {};
    this.children = [];
    this.parent = null;
    this.text = '';
    this.style = {};
    this.value = '';
    this.classList = new ClassList(this);
    this._scrolled = false;
  }
  get className() { return this.attrs.class || ''; }
  set className(v) { this.attrs.class = v; this.classList.from(v); }
  get id() { return this.attrs.id; }
  setAttrs(attrStr) {
    const re = /([^\s=]+)(?:\s*=\s*("([^"]*)"|'([^']*)'|[^\s"'>]+))?/g;
    let m;
    while ((m = re.exec(attrStr))) {
      const name = m[1];
      const val = m[3] !== undefined ? m[3] : m[4] !== undefined ? m[4] : (m[2] || '');
      this.attrs[name] = val;
      if (name === 'class') this.classList.from(val);
      else if (name.startsWith('data-')) this.dataset[camel(name.slice(5))] = val;
    }
  }
  get innerHTML() { return this._html || ''; }
  set innerHTML(v) { this.children = []; this.text = ''; this._html = v; parseInto(v, this, this.doc); }
  get textContent() {
    let t = this.text || '';
    for (const c of this.children) t += c.textContent;
    return t;
  }
  set textContent(v) { this.children = []; this.text = String(v); this._html = ''; }
  appendChild(c) { c.parent = this; this.children.push(c); }
  scrollIntoView() { this._scrolled = true; }
  focus() { this.doc.activeElement = this; }
  setSelectionRange() {}
  click() { if (this.onclick) this.onclick({ target: this, stopPropagation() {}, preventDefault() {} }); }
  addEventListener(t, fn) { (this._listeners ||= {})[t] = [...(this._listeners[t] || []), fn]; }
  fire(t, ev) { (this._listeners?.[t] || []).forEach(fn => fn(ev || { target: this })); }
  closest(sel) {
    let el = this;
    while (el) { if (matchSel(el, sel)) return el; el = el.parent; }
    return null;
  }
  querySelectorAll(sel) {
    const out = [];
    const walk = el => { for (const c of el.children) { if (matchSel(c, sel)) out.push(c); walk(c); } };
    walk(this);
    return out;
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

function parseInto(html, root, doc) {
  const stack = [root];
  const re = /<(\/?)([a-zA-Z0-9-]+)((?:[^"'>]|"[^"]*"|'[^']*')*?)(\/?)>|([^<]+)/g;
  let m;
  while ((m = re.exec(html))) {
    if (m[5] !== undefined) { stack[stack.length - 1].text += m[5]; continue; }
    const [, closing, tag, attrStr, selfClose] = m;
    const top = stack[stack.length - 1];
    if (closing) {
      // pop to matching tag (tolerant)
      for (let i = stack.length - 1; i > 0; i--)
        if (stack[i].tagName === tag.toUpperCase()) { stack.length = i; break; }
      continue;
    }
    const el = new El(tag, doc);
    el.setAttrs(attrStr);
    top.appendChild(el);
    if (!selfClose && !VOID.has(tag.toLowerCase())) stack.push(el);
  }
}

// ---- selector matching ---------------------------------------------------
// supports: lists (a,b), descendant combinator, #id, .class, tag,
// [name="v"], and compounds like .board-card[data-id="x"]
function matchSimple(el, s) {
  const re = /([#.]?[\w-]+)|\[\s*([\w-]+)\s*=\s*["']?([^"'\]]*)["']?\s*\]/g;
  let m, matched = 0, total = 0;
  while ((m = re.exec(s))) {
    total++;
    if (m[2] !== undefined) {
      const v = m[2].startsWith('data-') ? el.dataset[camel(m[2].slice(5))] : el.attrs[m[2]];
      if (v === m[3]) matched++;
    } else {
      const t = m[1];
      let ok;
      if (t.startsWith('.')) ok = el.classList.contains(t.slice(1));
      else if (t.startsWith('#')) ok = el.id === t.slice(1);
      else ok = el.tagName === t.toUpperCase();
      if (ok) matched++;
    }
  }
  return total > 0 && matched === total;
}

function matchChain(el, parts) {
  // parts[0] is the rightmost simple selector
  if (!matchSimple(el, parts[0])) return false;
  let anc = el.parent;
  for (let i = 1; i < parts.length && anc; i++) {
    while (anc && !matchSimple(anc, parts[i])) anc = anc.parent;
    if (!anc) return false;
    anc = anc.parent;
  }
  return true;
}

function matchSel(el, sel) {
  return sel.split(',').some(part => {
    const chain = part.trim().split(/\s+/).reverse();
    return matchChain(el, chain);
  });
}

// ---- document stub -------------------------------------------------------
function makeDoc(bodyHtml) {
  const doc = {
    activeElement: null,
    hidden: false,
    listeners: {},
    addEventListener(t, fn) { (doc.listeners[t] ||= []).push(fn); },
  };
  doc.root = new El('body', doc);
  parseInto(bodyHtml, doc.root, doc);
  doc.getElementById = id => {
    let found = null;
    const walk = el => { for (const c of el.children) { if (c.id === id) { found = c; return; } walk(c); } };
    walk(doc.root);
    return found;
  };
  doc.querySelectorAll = sel => doc.root.querySelectorAll(sel);
  doc.querySelector = sel => doc.root.querySelector(sel);
  return doc;
}

// ---- boot the page script in a vm ---------------------------------------
function boot(storeInit = {}) {
  const bodyHtml = htmlSrc.split('<body')[1].replace(/^[^>]*>/, '').replace(/<\/body>[\s\S]*$/, '')
    .replace(/<script[\s\S]*?<\/script>/gi, '').replace(/<style[\s\S]*?<\/style>/gi, '');
  const script = [...htmlSrc.matchAll(/<script>([\s\S]*?)<\/script>/g)].pop()[1];

  const doc = makeDoc(bodyHtml);
  const store = { ...storeInit };
  const localStorage = {
    getItem: k => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    _store: store,
  };
  const ctx = {
    document: doc,
    localStorage,
    navigator: {},
    location: { reload() { ctx._reloaded = true; } },
    CSS: { escape: s => String(s).replace(/["\\\]]/g, c => '\\' + c) },
    fetch: async () => ({ ok: true, json: async () => payload }),
    setTimeout: (fn) => 0,          // don't run deferred callbacks
    setInterval: () => 0,
    clearTimeout: () => {},
    AbortController,
    console,
    _reloaded: false,
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(script, ctx, { timeout: 5000 });
  return { ctx, doc, localStorage, store };
}

const tick = () => new Promise(r => setImmediate(r));
const AUTO_RE = /^(cms|logs|gev|vcast|disk)-auto-|-auto-health$/;

let pass = 0, fail = 0;
const DEBUG = process.env.BOARD_TEST_DEBUG === "1";
const ok = (cond, name) => { if (cond) { pass++; console.log('  ok', name); } else { fail++; console.log('  FAIL', name); } };

const cardsByCol = col => payload.cards.filter(c => (c.column || 'backlog') === col);
const autoByCol = col => cardsByCol(col).filter(c => AUTO_RE.test(c.id));
const normByCol = col => cardsByCol(col).filter(c => !AUTO_RE.test(c.id));
const colIds = payload.columns.map(c => c.id);
const domCards = doc => doc.querySelectorAll('.board-card');
const domCardIds = doc => domCards(doc).map(e => e.dataset.id);
const togs = doc => doc.querySelectorAll('.auto-tog');

// ---------- 1. default collapsed grouping --------------------------------
{
  const { doc } = boot();
  await tick(); await tick();
  const ids = domCardIds(doc);
  for (const col of colIds) {
    const want = normByCol(col).map(c => c.id);
    ok(want.every(id => ids.includes(id)), `col ${col}: all ${want.length} human cards rendered`);
    const autos = autoByCol(col);
    ok(autos.every(c => !ids.includes(c.id)), `col ${col}: ${autos.length} auto cards hidden (collapsed)`);
    if (autos.length) {
      const tog = togs(doc).find(t => t.dataset.col === col);
      ok(tog && tog.textContent.includes(`automation (${autos.length})`),
         `col ${col}: header "automation (${autos.length})" — got "${tog && tog.textContent.trim()}"`);
      ok(tog.textContent.includes('▸'), `col ${col}: collapsed caret`);
    }
  }
  const wantAll = payload.cards.filter(c => !AUTO_RE.test(c.id)).length;
  if (DEBUG && ids.length !== wantAll) {
    const want = new Set(payload.cards.filter(c => !AUTO_RE.test(c.id)).map(c => c.id));
    console.log('  extra:', ids.filter(i => !want.has(i)));
    console.log('  dupes:', ids.filter((i, n) => ids.indexOf(i) !== n));
    console.log('  rendered', ids.length, 'want', wantAll);
  }
  ok(ids.length === wantAll, 'total rendered == human cards only');
}

// ---------- 2. toggle expands + persists ----------------------------------
{
  const { doc, store } = boot();
  await tick(); await tick();
  const col = colIds.find(c => autoByCol(c).length);
  togs(doc).find(t => t.dataset.col === col).click();
  const ids = domCardIds(doc);
  const autos = autoByCol(col);
  ok(autos.every(c => ids.includes(c.id)), `toggle: ${autos.length} auto cards now in DOM for ${col}`);
  ok(JSON.parse(store['board-auto-open'] || '{}')[col] === true,
     `toggle persisted autoOpen.${col}=true to localStorage`);
  const tog = togs(doc).find(t => t.dataset.col === col);
  ok(tog.textContent.includes('▾'), 'expanded caret after toggle');
}

// ---------- 3. persisted state survives reload ----------------------------
{
  const col = colIds.filter(c => autoByCol(c).length).pop();
  const { doc } = boot({ 'board-auto-open': JSON.stringify({ [col]: true }) });
  await tick(); await tick();
  const ids = domCardIds(doc);
  const autos = autoByCol(col);
  ok(autos.every(c => ids.includes(c.id)), `boot with persisted state: ${col} group starts expanded`);
}

// ---------- 4. sidebar click auto-expands a collapsed card ---------------
{
  const { doc, store } = boot();
  await tick(); await tick();
  // pick a column with auto cards not already open
  const col = colIds.find(c => autoByCol(c).length && !domCardIds(doc).includes(autoByCol(c)[0].id));
  const target = autoByCol(col)[0];
  const side = doc.querySelectorAll('.side-card').find(e => e.dataset.id === target.id);
  ok(!!side, `sidebar lists collapsed auto card ${target.id}`);
  side.click();
  const el = doc.querySelectorAll('.board-card').find(e => e.dataset.id === target.id);
  ok(!!el, 'sidebar click: auto card now in DOM');
  ok(el && el._scrolled, 'sidebar click: scrollIntoView reached the card');
  ok(JSON.parse(store['board-auto-open'] || '{}')[col] === true,
     'sidebar click persisted the expansion');
  const body = doc.getElementById('card-modal-body');
  ok(body.innerHTML.includes(target.id), 'sidebar click opened the card modal');
}

// ---------- 5. filter reveals collapsed group matches --------------------
{
  const { doc } = boot();
  await tick(); await tick();
  const col = colIds.find(c => autoByCol(c).length);
  const target = autoByCol(col)[0];
  const filter = doc.getElementById('card-filter');
  filter.value = target.id;
  filter.fire('input');
  const el = doc.querySelectorAll('.board-card').find(e => e.dataset.id === target.id);
  ok(!!el, 'filter match: collapsed auto card rendered via re-render');
  ok(el && el.style.display !== 'none', 'filter match: card not display:none');
}

// ---------- 6. count badge sanity ----------------------------------------
{
  const { doc } = boot();
  await tick(); await tick();
  for (const col of colIds) {
    const autos = autoByCol(col);
    const tog = togs(doc).find(t => t.dataset.col === col);
    if (!autos.length) { ok(!tog, `col ${col}: no group header when 0 auto cards`); continue; }
    const m = tog && tog.textContent.match(/automation \((\d+)\)/);
    ok(m && +m[1] === autos.length, `col ${col}: badge count ${autos.length} correct`);
  }
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
