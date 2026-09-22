// chaba-log-card — full-height HA logbook for the chaba-admin Log tab.
//
// Wraps the native logbook card so the card always fills the viewport
// (use a `type: panel` view) and the log entries scroll inside the card
// while the header and filter row stay fixed.
//
// Filter: one checkbox per entity domain found in config.entities
// (input_* grouped as "input"). Hidden groups are persisted cross-device
// in input_text.chaba_events_filter JSON under "log_hidden" — writes merge
// so the events card's "hidden" key is preserved.
class ChabaLogCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._entities = this._config.entities || [];
    this._filterEntity =
      this._config.filter_entity || "input_text.chaba_events_filter";
    this._inner = null;

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
      .clc-filters { display:flex; flex-wrap:wrap; gap:4px 14px;
        padding:2px 16px 10px; flex:0 0 auto; }
      .clc-filters label { display:flex; align-items:center; gap:5px;
        font-size:.85rem; cursor:pointer; color:var(--primary-text-color); }
      .clc-content { flex:1; min-height:0; overflow-y:auto; padding:0 8px 8px; }
      .clc-err { padding:8px 16px; color:var(--error-color,#f47067); font-size:.85rem; }
    `;
    this._filters = document.createElement("div");
    this._filters.className = "clc-filters";
    this._content = document.createElement("div");
    this._content.className = "clc-content";
    this._card.append(style, this._filters, this._content);
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

  async _buildInner() {
    if (!window.loadCardHelpers) {
      this._content.innerHTML =
        '<div class="clc-err">loadCardHelpers unavailable</div>';
      return;
    }
    const helpers = await window.loadCardHelpers();
    const hidden = this._hiddenGroups();
    const entities = this._entities.filter(
      (e) => !hidden.has(this._group(e))
    );
    const el = helpers.createCardElement({
      type: "logbook",
      hours_to_show: this._config.hours_to_show || 24,
      entities,
    });
    if (this._hass) el.hass = this._hass;
    el.__flattened = false;
    this._flatten(el);
    this._inner = el;
    this._content.innerHTML = "";
    this._content.appendChild(el);
  }

  // Strip the inner card's chrome (border/shadow/header) — the outer
  // ha-card supplies it. Lit renders around foreign children, so the
  // injected <style> survives inner re-renders.
  _flatten(el) {
    const apply = () => {
      const sr = el.shadowRoot;
      if (!sr || el.__flattened) return;
      const s = document.createElement("style");
      s.textContent =
        "ha-card{box-shadow:none;border:none;background:transparent;" +
        "--ha-card-border-width:0}h1,.card-header{display:none}";
      sr.appendChild(s);
      el.__flattened = true;
    };
    apply();
    requestAnimationFrame(apply);
  }

  _renderFilters() {
    if (!this._filters) return;
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
        this._buildInner();
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
    } else if (this._inner) {
      this._inner.hass = hass;
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
  description: "Full-height scrollable HA logbook with domain filters",
});
