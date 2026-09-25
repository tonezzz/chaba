// chaba-report-card — hierarchical system report for the chaba-home
// Report tab. Fetches /local/chaba-report.json (rendered by
// scripts/chaba/render-report-feed.py) and shows it as an indented
// expand/collapse tree: layer rows with badge + one-line summary;
// clicking expands children, then leaf body text.
//
// Designed for a `type: panel` view: toolbar fixed, the tree scrolls
// internally; height is JS-measured (light DOM — all rules scoped under
// the tag name, same pattern as chaba-events-card).
//
// Config: title, url (default /local/chaba-report.json),
//         poll_seconds (default 30), expanded (default true =
//         top-level layers start expanded)
class ChabaReportCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._feedUrl = this._config.url || "/local/chaba-report.json";
    this._feed = null;
    this._err = null;
    this._open = new Set();           // ids of expanded nodes
    this._seeded = false;

    this._card = document.createElement("ha-card");
    this._card.header = this._config.title || "System report";

    const style = document.createElement("style");
    style.textContent = `
      chaba-report-card { display:flex; flex-direction:column; height:100%;
        min-height:calc(100vh - var(--header-height, 56px) - 56px); }
      chaba-report-card > ha-card { display:flex; flex-direction:column;
        flex:1; min-height:0; }
      chaba-report-card .bar { display:flex; align-items:center; gap:10px;
        padding:0 16px 8px; flex:0 0 auto; font-size:.8rem;
        color:var(--secondary-text-color); }
      chaba-report-card .bar button { font:inherit; font-size:.78rem;
        color:var(--primary-text-color);
        background:var(--secondary-background-color,rgba(0,0,0,.06));
        border:1px solid var(--divider-color,#666); border-radius:6px;
        padding:2px 10px; cursor:pointer; }
      chaba-report-card .tree { flex:1; min-height:0; overflow-y:auto;
        padding:0 16px 16px; }
      chaba-report-card .head { display:flex; align-items:center; gap:8px;
        padding:6px 8px; cursor:pointer; border-radius:6px; }
      chaba-report-card .head:hover {
        background:var(--secondary-background-color,rgba(0,0,0,.08)); }
      chaba-report-card .tw { width:14px; flex:0 0 auto;
        color:var(--secondary-text-color); font-size:.8rem;
        text-align:center; }
      chaba-report-card .ti { --mdc-icon-size:17px; flex:0 0 auto;
        color:var(--secondary-text-color); }
      chaba-report-card .name { font-weight:500; }
      chaba-report-card .badge { font-size:.68rem; padding:0 7px;
        border-radius:9px; background:var(--primary-color);
        color:var(--text-primary-color,#fff); white-space:nowrap; }
      chaba-report-card .sum { flex:1; min-width:0; overflow:hidden;
        text-overflow:ellipsis; white-space:nowrap; font-size:.8rem;
        color:var(--secondary-text-color); }
      chaba-report-card .body { margin:2px 8px 8px 30px; padding:8px 10px;
        border-radius:6px; font-size:.8rem; white-space:pre-wrap;
        word-break:break-word; color:var(--primary-text-color);
        background:var(--secondary-background-color,rgba(0,0,0,.06)); }
      chaba-report-card .meta { margin:0 8px 6px 30px; font-size:.72rem;
        color:var(--secondary-text-color); }
      chaba-report-card .meta span { margin-right:10px; }
      chaba-report-card .err { color:var(--error-color,#f47067);
        font-size:.85rem; padding:8px 0; }
    `;

    const bar = document.createElement("div");
    bar.className = "bar";
    this._gen = document.createElement("span");
    this._gen.style.cssText = "flex:1";
    const all = document.createElement("button");
    all.textContent = "expand all";
    all.onclick = () => this._expandAll();
    const none = document.createElement("button");
    none.textContent = "collapse";
    none.onclick = () => { this._open.clear(); this._render(); };
    const refresh = document.createElement("button");
    refresh.textContent = "refresh";
    refresh.onclick = () => this._load();
    bar.append(this._gen, all, none, refresh);

    this._tree = document.createElement("div");
    this._tree.className = "tree";
    this._card.append(style, bar, this._tree);
    this.appendChild(this._card);

    this._load();
    this._poll = setInterval(() => this._load(),
      (this._config.poll_seconds || 30) * 1000);
  }

  connectedCallback() {
    this._onResize = () => this._fitHeight();
    window.addEventListener("resize", this._onResize);
    if (window.visualViewport)
      window.visualViewport.addEventListener("resize", this._onResize);
    this._fitHeight();
    requestAnimationFrame(() => this._fitHeight());
    setTimeout(() => this._fitHeight(), 300);
  }

  disconnectedCallback() {
    clearInterval(this._poll);
    window.removeEventListener("resize", this._onResize);
    if (window.visualViewport)
      window.visualViewport.removeEventListener("resize", this._onResize);
  }

  _fitHeight() {
    const r = this.getBoundingClientRect();
    const vv = window.visualViewport;
    let bottom = vv ? vv.offsetTop + vv.height : window.innerHeight;
    const p = this.parentElement;
    if (p) {
      const pr = p.getBoundingClientRect();
      const padB = parseFloat(getComputedStyle(p).paddingBottom) || 0;
      bottom = Math.min(bottom, pr.bottom - padB);
    }
    const h = Math.max(150, Math.floor(bottom - r.top));
    if (h > 0) this.style.height = h + "px";
  }

  async _load() {
    try {
      const r = await fetch(this._feedUrl + "?t=" + Date.now());
      if (!r.ok) throw new Error("HTTP " + r.status);
      this._feed = await r.json();
      this._err = null;
    } catch (e) {
      this._err = e.message || String(e);
    }
    this._render();
  }

  _allIds(ns, acc) {
    for (const n of ns || []) {
      acc.add(n.id);
      this._allIds(n.children, acc);
    }
  }

  _expandAll() {
    this._allIds(this._feed && this._feed.layers, this._open);
    this._render();
  }

  _render() {
    const t = this._tree;
    t.innerHTML = "";
    if (this._err) {
      const d = document.createElement("div");
      d.className = "err";
      d.textContent = "Feed error: " + this._err;
      t.appendChild(d);
      return;
    }
    if (!this._feed) return;
    this._gen.textContent =
      "generated " + (this._feed.generated_at || "?")
        .slice(0, 16).replace("T", " ");
    const layers = this._feed.layers || [];
    if (!this._seeded) {
      // default: top-level layers expanded, their children collapsed
      this._seeded = true;
      if (this._config.expanded !== false)
        for (const l of layers) this._open.add(l.id);
    }
    for (const l of layers) t.appendChild(this._node(l, 0));
  }

  _node(n, depth) {
    const kids = n.children || [];
    const wrap = document.createElement("div");
    const open = this._open.has(n.id);

    const head = document.createElement("div");
    head.className = "head";
    head.style.paddingLeft = (depth * 14 + 8) + "px";
    const tw = document.createElement("span");
    tw.className = "tw";
    tw.textContent = (kids.length || n.body) ? (open ? "▾" : "▸") : "·";
    const ic = document.createElement("ha-icon");
    ic.className = "ti";
    ic.setAttribute("icon", n.icon || "mdi:circle-outline");
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = n.title || n.id;
    head.append(tw, ic, name);
    if (n.badge != null && n.badge !== "") {
      const b = document.createElement("span");
      b.className = "badge";
      b.textContent = n.badge;
      head.appendChild(b);
    }
    if (n.summary) {
      const s = document.createElement("span");
      s.className = "sum";
      s.textContent = n.summary;
      head.appendChild(s);
    }
    head.onclick = () => {
      if (open) this._open.delete(n.id); else this._open.add(n.id);
      this._render();
    };
    wrap.appendChild(head);

    if (open) {
      if (n.meta) {
        const m = document.createElement("div");
        m.className = "meta";
        for (const [k, v] of Object.entries(n.meta)) {
          const s = document.createElement("span");
          s.textContent = k + ": " +
            (Array.isArray(v) ? v.join(", ") : String(v));
          m.appendChild(s);
        }
        wrap.appendChild(m);
      }
      if (n.body) {
        const b = document.createElement("div");
        b.className = "body";
        b.textContent = n.body;
        wrap.appendChild(b);
      }
      for (const c of kids) wrap.appendChild(this._node(c, depth + 1));
    }
    return wrap;
  }

  set hass(hass) { this._hass = hass; }
  getCardSize() { return 6; }
}

customElements.define("chaba-report-card", ChabaReportCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "chaba-report-card",
  name: "Chaba Report",
  description: "Hierarchical system report tree (expand/collapse)",
});
