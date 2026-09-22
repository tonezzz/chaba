// chaba-log-card — isolated copy of the built-in /logbook page for the
// chaba-admin Log tab, so its UX/UI can be modified freely.
//
// Uses the same <ha-logbook> element and logbook/event_stream backend as
// the native page, wrapped in our own chrome: a fixed toolbar (range
// presets / custom datetime range / refresh / entity text filter) plus a
// per-domain checkbox row — the list scrolls inside the card. Designed
// for a `type: panel` view so the card fills the viewport; height is
// JS-measured (see _fitHeight) because this card renders light-DOM and
// :host selectors do not apply.
//
// Data model: .time = {recent: seconds} for live tailing (the presets) or
// {range: [Date, Date]} for a fixed window (custom). ha-logbook manages
// its own subscription; changing .time/.entityIds resubscribes in place.
//
// Filter: one checkbox per entity domain found in config.entities
// (input_* grouped as "input"), plus a substring text filter. Hidden
// groups persist cross-device in input_text.chaba_events_filter JSON
// under "log_hidden" — writes merge so the events card's "hidden" key is
// preserved. If config.entities is omitted the whole logbook is shown and
// the domain row is skipped.
class ChabaLogCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._entities = this._config.entities || null;
    this._filterEntity =
      this._config.filter_entity || "input_text.chaba_events_filter";
    this._mode = { recent: (this._config.hours_to_show || 24) * 3600 };
    this._entText = "";
    this._lb = null;

    this._card = document.createElement("ha-card");
    this._card.header = this._config.title || "Logbook";
    const style = document.createElement("style");
    // NOTE: light DOM (no shadow root) — :host matches nothing here, so the
    // element is styled via its tag name and all classes are clc- prefixed.
    style.textContent = `
      chaba-log-card { display:flex; flex-direction:column; height:100%;
        min-height:calc(100vh - var(--header-height, 56px) - 56px); }
      chaba-log-card > ha-card { display:flex; flex-direction:column;
        flex:1; min-height:0; }
      .clc-bar { display:flex; flex-wrap:wrap; align-items:center;
        gap:6px 10px; padding:0 16px 8px; flex:0 0 auto; }
      .clc-bar select, .clc-bar input, .clc-bar button {
        font:inherit; font-size:.82rem; color:var(--primary-text-color);
        background:var(--secondary-background-color,rgba(0,0,0,.06));
        border:1px solid var(--divider-color,#666); border-radius:6px;
        padding:3px 8px; }
      .clc-bar button { cursor:pointer; }
      .clc-bar button:hover { border-color:var(--primary-color); }
      .clc-ent { min-width:140px; flex:0 1 200px; }
      .clc-dt, .clc-apply { display:none; }
      chaba-log-card[data-range="custom"] .clc-dt,
      chaba-log-card[data-range="custom"] .clc-apply { display:inline-block; }
      .clc-filters { display:flex; flex-wrap:wrap; gap:4px 14px;
        padding:0 16px 8px; flex:0 0 auto; }
      .clc-filters label { display:flex; align-items:center; gap:5px;
        font-size:.85rem; cursor:pointer; color:var(--primary-text-color); }
      .clc-content { flex:1; min-height:0; overflow-y:auto; padding:0 8px 8px; }
      .clc-content ha-logbook { display:block; height:100%; }
      .clc-err { padding:8px 16px; color:var(--error-color,#f47067);
        font-size:.85rem; }
    `;
    this._card.append(style);

    // toolbar: range presets / custom range / refresh / entity text filter
    const bar = document.createElement("div");
    bar.className = "clc-bar";

    this._rangeSel = document.createElement("select");
    for (const [v, l] of [
      ["3600", "Live · 1h"],
      ["86400", "Live · 24h"],
      ["604800", "Live · 7d"],
      ["custom", "Custom…"],
    ]) {
      const o = document.createElement("option");
      o.value = v;
      o.textContent = l;
      if (v === String(this._mode.recent)) o.selected = true;
      this._rangeSel.appendChild(o);
    }
    this._rangeSel.onchange = () => this._rangeChanged();

    this._from = document.createElement("input");
    this._from.type = "datetime-local";
    this._from.className = "clc-dt";
    this._to = document.createElement("input");
    this._to.type = "datetime-local";
    this._to.className = "clc-dt";
    const apply = document.createElement("button");
    apply.className = "clc-apply";
    apply.textContent = "Apply";
    apply.onclick = () => this._applyCustomRange();

    const refresh = document.createElement("button");
    refresh.textContent = "⟳";
    refresh.title = "Refresh";
    refresh.onclick = () => this._lb && this._lb.refresh(true);

    this._entInput = document.createElement("input");
    this._entInput.type = "search";
    this._entInput.className = "clc-ent";
    this._entInput.placeholder = "entity filter";
    this._entInput.oninput = () => {
      clearTimeout(this._entDeb);
      this._entDeb = setTimeout(() => {
        this._entText = this._entInput.value.trim().toLowerCase();
        this._applyState();
      }, 350);
    };

    bar.append(this._rangeSel, this._from, this._to, apply, refresh,
      this._entInput);
    this._card.appendChild(bar);

    this._filters = document.createElement("div");
    this._filters.className = "clc-filters";
    this._card.appendChild(this._filters);

    this._content = document.createElement("div");
    this._content.className = "clc-content";
    this._card.appendChild(this._content);
    this.appendChild(this._card);
  }

  connectedCallback() {
    this._onResize = () => this._fitHeight();
    window.addEventListener("resize", this._onResize);
    // iOS Safari: innerHeight includes space hidden under the browser
    // toolbar; visualViewport tracks the actually-visible area (and fires
    // resize when the toolbar shows/hides).
    if (window.visualViewport) {
      window.visualViewport.addEventListener("resize", this._onResize);
    }
    this._fitHeight();
    // settle after the view finishes layout (top edge moves into place)
    requestAnimationFrame(() => this._fitHeight());
    setTimeout(() => this._fitHeight(), 300);
  }

  disconnectedCallback() {
    window.removeEventListener("resize", this._onResize);
    if (window.visualViewport) {
      window.visualViewport.removeEventListener("resize", this._onResize);
    }
    clearTimeout(this._entDeb);
  }

  // Fit exactly to the space the layout allocated: fill down to our
  // parent's content-box bottom (honors whatever padding the view uses),
  // clamped to the visual viewport so iOS toolbars don't leave a gap or
  // push the card under the edge.
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
    if (this._lb) this._lb.narrow = this.offsetWidth < 870;
  }

  _rangeChanged() {
    const v = this._rangeSel.value;
    this.dataset.range = v === "custom" ? "custom" : "live";
    if (v === "custom") {
      const now = new Date();
      const fmt = (d) => {
        const p = (n) => String(n).padStart(2, "0");
        return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}` +
          `T${p(d.getHours())}:${p(d.getMinutes())}`;
      };
      this._to.value = fmt(now);
      this._from.value = fmt(new Date(now.getTime() - 86400000));
      return;
    }
    this._mode = { recent: parseInt(v, 10) };
    this._applyState();
  }

  _applyCustomRange() {
    const a = new Date(this._from.value);
    const b = new Date(this._to.value);
    if (isNaN(a) || isNaN(b) || a >= b) return;
    this._mode = { range: [a, b] };
    this._applyState();
  }

  _group(eid) {
    const d = String(eid).split(".")[0];
    return d.startsWith("input_") ? "input" : d;
  }

  _hiddenGroups() {
    const st = this._hass && this._hass.states[this._filterEntity];
    try {
      const j = JSON.parse((st && st.state) || "{}");
      return new Set(Array.isArray(j.log_hidden) ? j.log_hidden : []);
    } catch {
      return new Set();
    }
  }

  async _setHiddenGroups(hidden) {
    if (!this._hass) return;
    let j = {};
    try {
      j = JSON.parse(this._hass.states[this._filterEntity]?.state || "{}");
    } catch {}
    j.log_hidden = [...hidden];
    await this._hass.callService("input_text", "set_value", {
      entity_id: this._filterEntity,
      value: JSON.stringify(j),
    });
  }

  _visibleEntities() {
    if (!this._entities) return undefined; // no list -> whole logbook
    const hidden = this._hiddenGroups();
    return this._entities.filter(
      (e) =>
        !hidden.has(this._group(e)) &&
        (!this._entText || e.toLowerCase().includes(this._entText))
    );
  }

  // hui-logbook-card imports ha-logbook — creating it via the card helpers
  // forces the module (and the ha-logbook element) to load.
  async _ensureLogbook() {
    if (customElements.get("ha-logbook")) return true;
    try {
      const helpers = await window.loadCardHelpers();
      helpers.createCardElement({ type: "logbook", entities: ["sun.sun"] });
      await Promise.race([
        customElements.whenDefined("ha-logbook"),
        new Promise((r) => setTimeout(r, 5000)),
      ]);
    } catch { /* fall through */ }
    return !!customElements.get("ha-logbook");
  }

  async _buildInner() {
    const ok = await this._ensureLogbook();
    if (!ok) {
      this._content.innerHTML =
        '<div class="clc-err">ha-logbook element unavailable</div>';
      return;
    }
    const el = document.createElement("ha-logbook");
    el.setAttribute("virtualize", "");
    el.showCause = true;
    const empty = document.createElement("div");
    empty.slot = "empty";
    empty.className = "clc-err";
    empty.textContent = "No logbook entries for this selection.";
    el.appendChild(empty);
    this._lb = el;
    this._applyState();
    this._content.innerHTML = "";
    this._content.appendChild(el);
  }

  _applyState() {
    if (!this._lb || !this._hass) return;
    this._lb.hass = this._hass;
    this._lb.entityIds = this._visibleEntities();
    this._lb.time =
      "recent" in this._mode
        ? { recent: this._mode.recent }
        : { range: this._mode.range };
  }

  _renderFilters() {
    if (!this._filters) return;
    if (!this._entities) {
      this._filters.innerHTML = "";
      return;
    }
    const hidden = this._hiddenGroups();
    const groups = new Set(this._entities.map((e) => this._group(e)));
    this._filters.innerHTML = "";
    for (const g of [...groups].sort()) {
      const lb = document.createElement("label");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = !hidden.has(g);
      cb.onchange = async () => {
        if (cb.checked) hidden.delete(g); else hidden.add(g);
        await this._setHiddenGroups(hidden);
        this._applyState();
      };
      lb.append(cb, document.createTextNode(g));
      this._filters.appendChild(lb);
    }
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      this._buildInner();
    } else if (this._lb) {
      this._lb.hass = hass; // ha-logbook ignores redundant hass updates
    }
    this._renderFilters();
    this._fitHeight();
  }

  getCardSize() {
    return 6;
  }
}

customElements.define("chaba-log-card", ChabaLogCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "chaba-log-card",
  name: "Chaba Log",
  description: "Isolated copy of the /logbook page with modifiable UX",
});
