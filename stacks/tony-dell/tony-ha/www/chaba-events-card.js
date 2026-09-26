// chaba-events-card — unified event feed for the chaba-admin Events tab.
//
// Sources:
//   1. /local/chaba-events.json  — written by scripts/chaba-event-log.py
//      (24h retention, capped). Events may carry requires_response/responded.
//   2. persistent_notification entities — always requires_response, dismissed
//      via persistent_notification.dismiss.
//
// Category visibility is shared across devices via input_text.chaba_events_filter
// (JSON {"hidden": [...], "log_hidden": [...], "src": "..."} — "log_hidden"
// belongs to chaba-log-card on the Log tab, "src" is this card's source
// dropdown; all writes merge rather than replace).
//
// Full-height like the Log tab: designed for a `type: panel` view, the
// header/toolbar stay fixed and .rows scrolls internally. Height is
// JS-measured (_fitHeight) because the card renders light-DOM and :host
// selectors don't apply — all rules are scoped under the tag name.
class ChabaEventsCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._feedUrl = this._config.url || "/local/chaba-events.json";
    this._filterEntity =
      this._config.filter_entity || "input_text.chaba_events_filter";
    this._events = [];
    this._fetchErr = null;

    this._card = document.createElement("ha-card");
    this._card.header = config.title || "Events";
    const style = document.createElement("style");
    style.textContent = `
      chaba-events-card { display:flex; flex-direction:column; height:100%;
        min-height:calc(100vh - var(--header-height, 56px) - 56px); }
      chaba-events-card > ha-card { display:flex; flex-direction:column;
        flex:1; min-height:0; }
      chaba-events-card .srcbar { display:flex; flex-wrap:wrap; align-items:center;
        gap:6px 10px; padding:0 16px 8px; flex:0 0 auto; }
      chaba-events-card .srcbar .lbl { font-size:.82rem; color:var(--secondary-text-color); }
      chaba-events-card .srcbar select, chaba-events-card .srcbar button {
        font:inherit; font-size:.82rem;
        color:var(--primary-text-color);
        background:var(--secondary-background-color,rgba(0,0,0,.06));
        border:1px solid var(--divider-color,#666); border-radius:6px;
        padding:3px 8px; }
      chaba-events-card .srcbar button { cursor:pointer; margin-left:auto; }
      /* fullscreen fallback for webviews without the Fullscreen API
         (iPhone Safari): the card covers the viewport instead. */
      chaba-events-card[data-fs="1"] { position:fixed; inset:0; z-index:999;
        background:var(--primary-background-color,#111); }
      chaba-events-card:fullscreen {
        background:var(--primary-background-color,#111); }
      chaba-events-card .filters { display:flex; flex-wrap:wrap; gap:4px 14px;
        padding:0 16px 8px; flex:0 0 auto; }
      chaba-events-card .filters label { display:flex; align-items:center; gap:5px; font-size:.85rem;
        cursor:pointer; color:var(--primary-text-color); }
      chaba-events-card .attn-banner { margin:0 16px 8px; padding:6px 10px; border-radius:8px;
        font-size:.85rem; font-weight:500; display:none; flex:0 0 auto; }
      chaba-events-card .attn-banner.on { display:block; background:var(--warning-color,#ffa726);
        color:var(--text-primary-color,#fff); animation:chaba-pulse 1.6s ease-in-out infinite; }
      chaba-events-card .rows { display:flex; flex-direction:column; gap:6px;
        padding:0 16px 16px; flex:1; min-height:0; overflow-y:auto; }
      chaba-events-card .ev { border-left:3px solid var(--divider-color,#444); padding:6px 10px;
        border-radius:6px; background:var(--secondary-background-color,rgba(0,0,0,.06)); }
      chaba-events-card .ev.warn { border-left-color:var(--warning-color,#ffa726); }
      chaba-events-card .ev.fail { border-left-color:var(--error-color,#f47067); }
      chaba-events-card .ev.need { border-left-color:var(--error-color,#f47067);
        animation:chaba-pulse 1.6s ease-in-out infinite; }
      chaba-events-card .ev.responded { opacity:.55; animation:none; }
      chaba-events-card .ev .top { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
      chaba-events-card .ev .t { font-weight:500; flex:1; min-width:120px; }
      chaba-events-card .ev .ts { font-size:.75rem; color:var(--secondary-text-color); white-space:nowrap; }
      chaba-events-card .chip { font-size:.7rem; padding:1px 7px; border-radius:10px;
        background:var(--primary-color); color:var(--text-primary-color,#fff); }
      chaba-events-card .chip.src { background:transparent; color:var(--secondary-text-color);
        border:1px solid var(--divider-color,#666); }
      chaba-events-card .chip.conf-low { background:transparent; color:var(--warning-color,#ffa726);
        border:1px solid var(--warning-color,#ffa726); }
      chaba-events-card .ev .body { font-size:.82rem; color:var(--secondary-text-color);
        margin-top:3px; white-space:pre-wrap; display:none; }
      chaba-events-card .ev.open .body { display:block; }
      chaba-events-card .ev button { font-size:.75rem; padding:2px 10px; border:none; border-radius:6px;
        cursor:pointer; background:var(--primary-color); color:var(--text-primary-color,#fff); }
      chaba-events-card .ev button.ghost { background:transparent; color:var(--secondary-text-color);
        border:1px solid var(--divider-color,#666); }
      chaba-events-card .empty, chaba-events-card .err { color:var(--secondary-text-color); font-size:.85rem; }
      chaba-events-card .err { color:var(--error-color,#f47067); }
      @keyframes chaba-pulse {
        0%,100% { box-shadow:0 0 0 0 rgba(244,112,103,.45); }
        50% { box-shadow:0 0 10px 3px rgba(244,112,103,.55); }
      }
      @media (prefers-reduced-motion: reduce) {
        chaba-events-card .ev.need, chaba-events-card .attn-banner.on { animation:none;
          box-shadow:0 0 0 2px var(--error-color,#f47067); }
      }
    `;
    this._srcbar = document.createElement("div");
    this._srcbar.className = "srcbar";
    const lbl = document.createElement("span");
    lbl.className = "lbl";
    lbl.textContent = "Source";
    this._srcSel = document.createElement("select");
    this._srcSel.onchange = () => this._setSrc(this._srcSel.value);
    const expand = document.createElement("button");
    expand.textContent = "⤢";
    expand.title = "Expand fullscreen";
    expand.onclick = () => this._toggleFs();
    this._srcbar.append(lbl, this._srcSel, expand);
    this._banner = document.createElement("div");
    this._banner.className = "attn-banner";
    this._filters = document.createElement("div");
    this._filters.className = "filters";
    this._rows = document.createElement("div");
    this._rows.className = "rows";
    this._card.append(style, this._srcbar, this._banner, this._filters,
      this._rows);
    this.appendChild(this._card);
    this._loadFeed();
    this._poll = setInterval(() => this._loadFeed(), 30000);
  }

  connectedCallback() {
    this._onResize = () => this._fitHeight();
    window.addEventListener("resize", this._onResize);
    // iOS Safari: innerHeight includes space hidden under the browser
    // toolbar; visualViewport tracks the actually-visible area.
    if (window.visualViewport) {
      window.visualViewport.addEventListener("resize", this._onResize);
    }
    this._onFsChange = () => this._fitHeight();
    document.addEventListener("fullscreenchange", this._onFsChange);
    document.addEventListener("webkitfullscreenchange", this._onFsChange);
    this._fitHeight();
    requestAnimationFrame(() => this._fitHeight());
    setTimeout(() => this._fitHeight(), 300);
  }

  disconnectedCallback() {
    clearInterval(this._poll);
    window.removeEventListener("resize", this._onResize);
    if (window.visualViewport) {
      window.visualViewport.removeEventListener("resize", this._onResize);
    }
    document.removeEventListener("fullscreenchange", this._onFsChange);
    document.removeEventListener("webkitfullscreenchange", this._onFsChange);
  }

  // Expand the card over the whole screen. Prefers the Fullscreen API
  // (drops browser chrome too); falls back to a fixed-position overlay
  // where element fullscreen isn't supported (iPhone Safari).
  async _toggleFs() {
    try {
      const fsEl =
        document.fullscreenElement || document.webkitFullscreenElement;
      if (this.dataset.fs === "1") {
        this.dataset.fs = "";
      } else if (fsEl === this) {
        const exit = document.exitFullscreen ||
          document.webkitExitFullscreen;
        if (exit) await exit.call(document);
      } else if (this.requestFullscreen) {
        await this.requestFullscreen();
      } else if (this.webkitRequestFullscreen) {
        this.webkitRequestFullscreen();
      } else {
        this.dataset.fs = "1";
      }
    } catch {
      this.dataset.fs = "1";
    }
    this._fitHeight();
  }

  // Fill down to the parent's content-box bottom (honors view padding),
  // clamped to the visual viewport so iOS toolbars don't leave a gap.
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

  async _loadFeed() {
    try {
      const r = await fetch(this._feedUrl + "?t=" + Date.now());
      this._events = r.ok ? await r.json() : [];
      this._fetchErr = r.ok ? null : `feed HTTP ${r.status}`;
    } catch (e) {
      this._fetchErr = e.message;
    }
    this._render();
  }

  _hidden() {
    const st = this._hass && this._hass.states[this._filterEntity];
    try {
      const j = JSON.parse((st && st.state) || "{}");
      return new Set(Array.isArray(j.hidden) ? j.hidden : []);
    } catch {
      return new Set();
    }
  }

  async _setHidden(hidden) {
    if (!this._hass) return;
    let j = {};
    try {
      j = JSON.parse(this._hass.states[this._filterEntity]?.state || "{}");
    } catch {}
    if (!Array.isArray(j.hidden)) j.hidden = [];
    j.hidden = [...hidden];
    await this._hass.callService("input_text", "set_value", {
      entity_id: this._filterEntity,
      value: JSON.stringify(j),
    });
  }

  _src() {
    const st = this._hass && this._hass.states[this._filterEntity];
    try {
      const j = JSON.parse((st && st.state) || "{}");
      return typeof j.src === "string" && j.src ? j.src : "all";
    } catch {
      return "all";
    }
  }

  async _setSrc(v) {
    if (!this._hass) return;
    let j = {};
    try {
      j = JSON.parse(this._hass.states[this._filterEntity]?.state || "{}");
    } catch {}
    j.src = v;
    await this._hass.callService("input_text", "set_value", {
      entity_id: this._filterEntity,
      value: JSON.stringify(j),
    });
    this._render();
  }

  _notifications() {
    if (!this._hass) return [];
    const out = [];
    for (const [eid, st] of Object.entries(this._hass.states)) {
      if (!eid.startsWith("persistent_notification.")) continue;
      out.push({
        id: "pn." + eid,
        ts: (st.attributes.created_at || st.last_changed || "").replace(" ", "T"),
        source: "home-assistant",
        category: "ha-notify",
        severity: "warn",
        title: st.attributes.title || st.attributes.friendly_name || eid,
        body: st.attributes.message || "",
        requires_response: true,
        responded: false,
        _pn: true,
      });
    }
    return out;
  }

  _merged() {
    const all = [...this._events, ...this._notifications()];
    const pending = all.filter((e) => e.requires_response && !e.responded);
    const rest = all
      .filter((e) => !(e.requires_response && !e.responded))
      .sort((a, b) => String(b.ts).localeCompare(String(a.ts)));
    return { pending, rest };
  }

  _render() {
    if (!this._hass) return;
    const m = this._merged();
    const { pending, rest } = m;
    const hidden = this._hidden();
    const cats = new Set(all_cats(m));

    // source dropdown — rebuilt each render as sources appear/disappear
    const src = this._src();
    const sources = new Set();
    for (const e of [...pending, ...rest]) {
      if (e.source) sources.add(e.source);
    }
    this._srcSel.innerHTML = "";
    const optAll = document.createElement("option");
    optAll.value = "all";
    optAll.textContent = "All sources";
    this._srcSel.appendChild(optAll);
    for (const s of [...sources].sort()) {
      const o = document.createElement("option");
      o.value = s;
      o.textContent = s;
      this._srcSel.appendChild(o);
    }
    const effSrc = src === "all" || sources.has(src) ? src : "all";
    this._srcSel.value = effSrc;

    // filters
    this._filters.innerHTML = "";
    for (const c of [...cats].sort()) {
      const lb = document.createElement("label");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = !hidden.has(c);
      cb.onchange = () => {
        if (cb.checked) hidden.delete(c); else hidden.add(c);
        this._setHidden(hidden);
      };
      lb.append(cb, document.createTextNode(c));
      this._filters.appendChild(lb);
    }

    // attention banner
    const nPending = pending.length;
    this._banner.classList.toggle("on", nPending > 0);
    this._banner.textContent = nPending
      ? `${nPending} event${nPending > 1 ? "s" : ""} need${nPending > 1 ? "" : "s"} your response`
      : "";

    // rows: pending pinned first (always visible), then filtered rest
    this._rows.innerHTML = "";
    const shown = [
      ...pending,
      ...rest.filter(
        (e) =>
          !hidden.has(e.category) &&
          (effSrc === "all" || (e.source || "") === effSrc)
      ),
    ];
    if (this._fetchErr) {
      const d = document.createElement("div");
      d.className = "err";
      d.textContent = `Feed error: ${this._fetchErr}`;
      this._rows.appendChild(d);
    }
    if (!shown.length) {
      const d = document.createElement("div");
      d.className = "empty";
      d.textContent = this._events.length || pending.length
        ? "All categories hidden."
        : "No events in the last 24 hours.";
      this._rows.appendChild(d);
      return;
    }
    for (const e of shown.slice(0, 200)) this._rows.appendChild(this._row(e));
  }

  _row(e) {
    const div = document.createElement("div");
    div.className =
      "ev " + (e.severity || "") +
      (e.requires_response && !e.responded ? " need" : "") +
      (e.responded ? " responded" : "");
    const top = document.createElement("div");
    top.className = "top";

    const cat = document.createElement("span");
    cat.className = "chip";
    cat.textContent = e.category;
    const title = document.createElement("span");
    title.className = "t";
    title.textContent = e.title;
    title.style.cursor = e.body ? "pointer" : "default";
    title.onclick = () => div.classList.toggle("open");
    const ts = document.createElement("span");
    ts.className = "ts";
    ts.textContent = fmtTs(e.ts);

    top.append(cat, title);
    if (e.source) {
      const s = document.createElement("span");
      s.className = "chip src";
      s.textContent = e.source;
      s.title = "source";
      top.appendChild(s);
    }
    if (e.confidence != null) {
      const c = document.createElement("span");
      c.className = "chip" + (e.confidence < 0.6 ? " conf-low" : " src");
      c.textContent = `${Math.round(e.confidence * 100)}%`;
      c.title = "confidence";
      top.appendChild(c);
    }
    top.appendChild(ts);

    if (e.link) {
      const a = document.createElement("a");
      a.href = e.link;
      a.textContent = "↗";
      a.style.cssText = "color:var(--primary-color);text-decoration:none";
      top.appendChild(a);
    }
    if (e.requires_response && !e.responded) {
      const ack = document.createElement("button");
      ack.textContent = e._pn ? "Dismiss" : (e.action ? "Approve" : "Ack");
      ack.onclick = async () => {
        // optimistic update — reconcile with the feed in the background
        e.responded = true;
        ack.disabled = true;
        this._render();
        try {
          if (e._pn) {
            await this._hass.callService("persistent_notification", "dismiss", {
              notification_id: e.id.slice(3),
            });
          } else {
            await this._hass.callService("shell_command", "chaba_event_ack", {
              id: e.id,
            });
          }
        } finally {
          this._loadFeed();
        }
      };
      top.appendChild(ack);
    } else if (e.requires_response && e.responded) {
      const done = document.createElement("span");
      done.className = "chip src";
      done.textContent = "ack'd";
      top.appendChild(done);
    }
    div.appendChild(top);
    if (e.body) {
      const b = document.createElement("div");
      b.className = "body";
      b.textContent = e.body;
      div.appendChild(b);
    }
    return div;
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
    this._fitHeight();
  }

  getCardSize() {
    return 4;
  }
}

function all_cats(m) {
  const s = new Set();
  for (const e of [...m.pending, ...m.rest]) s.add(e.category);
  return s;
}

function fmtTs(ts) {
  if (!ts) return "";
  let d = new Date(ts);
  if (isNaN(d)) d = new Date(ts.slice(0, 19));
  if (isNaN(d)) return ts.slice(5, 16);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  return sameDay
    ? d.toTimeString().slice(0, 5)
    : d.toISOString().slice(5, 10) + " " + d.toTimeString().slice(0, 5);
}

customElements.define("chaba-events-card", ChabaEventsCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "chaba-events-card",
  name: "Chaba Events",
  description: "Unified chaba event feed with category filters",
});
