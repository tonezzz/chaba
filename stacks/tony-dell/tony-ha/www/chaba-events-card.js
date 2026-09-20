// chaba-events-card — unified event feed for the chaba-admin Events tab.
//
// Sources:
//   1. /local/chaba-events.json  — written by scripts/chaba-event-log.py
//      (24h retention, capped). Events may carry requires_response/responded.
//   2. persistent_notification entities — always requires_response, dismissed
//      via persistent_notification.dismiss.
//
// Category visibility is shared across devices via input_text.chaba_events_filter
// (JSON {"hidden": [...]}). The "logbook" checkbox maps to
// input_boolean.chaba_events_show_logbook which gates the native logbook card
// on the same view.
class ChabaEventsCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._feedUrl = this._config.url || "/local/chaba-events.json";
    this._filterEntity =
      this._config.filter_entity || "input_text.chaba_events_filter";
    this._logbookEntity =
      this._config.logbook_entity || "input_boolean.chaba_events_show_logbook";
    this._events = [];
    this._fetchErr = null;

    this._card = document.createElement("ha-card");
    this._card.header = config.title || "Events";
    const style = document.createElement("style");
    style.textContent = `
      .filters { display:flex; flex-wrap:wrap; gap:4px 14px; padding:0 16px 8px; }
      .filters label { display:flex; align-items:center; gap:5px; font-size:.85rem;
        cursor:pointer; color:var(--primary-text-color); }
      .attn-banner { margin:0 16px 8px; padding:6px 10px; border-radius:8px;
        font-size:.85rem; font-weight:500; display:none; }
      .attn-banner.on { display:block; background:var(--warning-color,#ffa726);
        color:var(--text-primary-color,#fff); animation:chaba-pulse 1.6s ease-in-out infinite; }
      .rows { display:flex; flex-direction:column; gap:6px; padding:0 16px 16px; }
      .ev { border-left:3px solid var(--divider-color,#444); padding:6px 10px;
        border-radius:6px; background:var(--secondary-background-color,rgba(0,0,0,.06)); }
      .ev.warn { border-left-color:var(--warning-color,#ffa726); }
      .ev.fail { border-left-color:var(--error-color,#f47067); }
      .ev.need { border-left-color:var(--error-color,#f47067);
        animation:chaba-pulse 1.6s ease-in-out infinite; }
      .ev.responded { opacity:.55; animation:none; }
      .ev .top { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
      .ev .t { font-weight:500; flex:1; min-width:120px; }
      .ev .ts { font-size:.75rem; color:var(--secondary-text-color); white-space:nowrap; }
      .chip { font-size:.7rem; padding:1px 7px; border-radius:10px;
        background:var(--primary-color); color:var(--text-primary-color,#fff); }
      .chip.src { background:transparent; color:var(--secondary-text-color);
        border:1px solid var(--divider-color,#666); }
      .chip.conf-low { background:transparent; color:var(--warning-color,#ffa726);
        border:1px solid var(--warning-color,#ffa726); }
      .ev .body { font-size:.82rem; color:var(--secondary-text-color);
        margin-top:3px; white-space:pre-wrap; display:none; }
      .ev.open .body { display:block; }
      .ev button { font-size:.75rem; padding:2px 10px; border:none; border-radius:6px;
        cursor:pointer; background:var(--primary-color); color:var(--text-primary-color,#fff); }
      .ev button.ghost { background:transparent; color:var(--secondary-text-color);
        border:1px solid var(--divider-color,#666); }
      .empty, .err { padding:0 16px 16px; color:var(--secondary-text-color); font-size:.85rem; }
      .err { color:var(--error-color,#f47067); }
      @keyframes chaba-pulse {
        0%,100% { box-shadow:0 0 0 0 rgba(244,112,103,.45); }
        50% { box-shadow:0 0 10px 3px rgba(244,112,103,.55); }
      }
      @media (prefers-reduced-motion: reduce) {
        .ev.need, .attn-banner.on { animation:none;
          box-shadow:0 0 0 2px var(--error-color,#f47067); }
      }
    `;
    this._banner = document.createElement("div");
    this._banner.className = "attn-banner";
    this._filters = document.createElement("div");
    this._filters.className = "filters";
    this._rows = document.createElement("div");
    this._rows.className = "rows";
    this._card.append(style, this._banner, this._filters, this._rows);
    this.appendChild(this._card);
    this._loadFeed();
    this._poll = setInterval(() => this._loadFeed(), 30000);
  }

  disconnectedCallback() {
    clearInterval(this._poll);
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
    await this._hass.callService("input_text", "set_value", {
      entity_id: this._filterEntity,
      value: JSON.stringify({ hidden: [...hidden] }),
    });
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
    const { pending, rest } = this._merged();
    const hidden = this._hidden();
    const cats = new Set(all_cats(this._merged()));
    cats.add("logbook");

    // filters
    this._filters.innerHTML = "";
    for (const c of [...cats].sort()) {
      const lb = document.createElement("label");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = c === "logbook"
        ? this._hass.states[this._logbookEntity]?.state === "on"
        : !hidden.has(c);
      cb.onchange = () => {
        if (c === "logbook") {
          this._hass.callService("input_boolean",
            cb.checked ? "turn_on" : "turn_off",
            { entity_id: this._logbookEntity });
        } else {
          if (cb.checked) hidden.delete(c); else hidden.add(c);
          this._setHidden(hidden);
        }
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
    const shown = [...pending, ...rest.filter((e) => !hidden.has(e.category))];
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
      ack.textContent = e._pn ? "Dismiss" : "Ack";
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
