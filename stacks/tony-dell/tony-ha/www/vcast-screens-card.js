// vcast-screens-card — lists virtual cast displays registered on the
// input-bridge relay, plus pending (unpaired) displays showing a QR.
// Polls GET <api>/displays; actions: test-cast (nav/play pub), re-pair
// (push unpaired -> display shows its QR again), release (revoke key).
// Config: api (default https://tony-dell.taila0626a.ts.net/api/input-bridge),
//         refresh (seconds, default 5), test_play_url, test_nav_url
class VcastScreensCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._api = (this._config.api || "https://tony-dell.taila0626a.ts.net/api/input-bridge").replace(/\/+$/, "");
    this._refreshMs = Math.max(2, this._config.refresh || 5) * 1000;
    this._card = document.createElement("ha-card");
    this._card.header = this._config.title || "Virtual cast screens";
    this._list = document.createElement("div");
    this._list.style.cssText = "padding:0 16px 16px;display:flex;flex-direction:column;gap:6px";
    this._card.appendChild(this._list);
    this.appendChild(this._card);
    this._poll();
  }

  disconnectedCallback() { clearInterval(this._t); }
  connectedCallback() {
    clearInterval(this._t);
    this._t = setInterval(() => this._poll(), this._refreshMs);
  }
  set hass(hass) { this._hass = hass; }

  _adminKey() {
    let k = localStorage.getItem("vcast.admin_key") || "";
    if (!k) {
      k = prompt("Ada admin API key (stored in this browser only):", "") || "";
      if (k) localStorage.setItem("vcast.admin_key", k.trim());
    }
    return k.trim();
  }

  async _call(path, opts) {
    const r = await fetch(this._api + path, opts);
    return r.json().catch(() => ({}));
  }
  _pub(screen, msg) {
    return this._call("/pub", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ screen, msg }),
    });
  }

  async _poll() {
    if (!this.isConnected) return;
    let data;
    try { data = await this._call("/displays"); }
    catch (e) { this._renderError(e); return; }
    this._render(data);
  }

  _render(data) {
    const list = this._list;
    list.innerHTML = "";
    const screens = (data && data.screens) || [];
    const pending = (data && data.pending) || [];

    if (!screens.length && !pending.length) {
      const d = document.createElement("div");
      d.style.color = "var(--secondary-text-color)";
      d.innerHTML = "No screens yet — open <b>/apps/vcast/</b> on a device and scan the QR it shows.";
      list.appendChild(d);
      return;
    }

    for (const p of pending) {
      const row = this._row(`⏳ ${p.label || "display"} — waiting to pair`, true);
      const open = this._btn("Pair");
      open.title = "Open the claim page (same flow the on-screen QR starts)";
      open.onclick = () => window.open(`/apps/vcast/pair.html?sid=${encodeURIComponent(p.sid)}`, "_blank");
      row.appendChild(open);
      list.appendChild(row);
    }

    for (const s of screens) {
      const row = this._row(`Screen #${s.screen} — ${s.name}`, false);
      const meta = document.createElement("span");
      meta.style.cssText = "font-size:.7rem;color:var(--secondary-text-color);white-space:nowrap";
      meta.textContent = `${s.label || ""} ${s.connected ? "· online" : "· offline"} ${s.state !== "idle" ? "· " + s.state : ""}`;
      row.appendChild(meta);

      const playBtn = this._btn("▶");
      playBtn.title = "Cast test HLS stream";
      playBtn.onclick = async () => {
        const r = await this._pub(s.screen, {
          type: "play",
          url: this._config.test_play_url || "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8",
        });
        playBtn.textContent = r.delivered ? "✓" : "!";
        setTimeout(() => (playBtn.textContent = "▶"), 1500);
      };
      const navBtn = this._iconBtn("mdi:open-in-app");
      navBtn.title = "Cast a test page (iframe nav)";
      navBtn.onclick = () =>
        this._pub(s.screen, { type: "nav", url: this._config.test_nav_url || "https://tony-dell.taila0626a.ts.net/apps/" });
      const stopBtn = this._iconBtn("mdi:stop");
      stopBtn.title = "Stop casting — back to idle screen";
      stopBtn.onclick = () => this._pub(s.screen, { type: "stop" });
      const reBtn = this._iconBtn("mdi:qrcode");
      reBtn.title = "Re-pair — display drops its key and shows the claim QR again";
      reBtn.onclick = () => this._pub(s.screen, { type: "unpaired" });
      const del = this._btn("Revoke");
      del.style.color = "var(--error-color,#f47067)";
      del.onclick = async () => {
        if (!confirm(`Revoke ${s.name}? The display is unpaired immediately.`)) return;
        const admin = this._adminKey();
        if (!admin) return;
        const r = await this._call("/release", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ screen: s.screen, admin_key: admin }),
        });
        if (r.error) { localStorage.removeItem("vcast.admin_key"); alert("Release failed: " + r.error); }
        this._poll();
      };
      row.append(playBtn, navBtn, stopBtn, reBtn, del);
      list.appendChild(row);
    }
  }

  _renderError(e) {
    this._list.innerHTML = "";
    const d = document.createElement("div");
    d.style.color = "var(--error-color,#f47067)";
    d.textContent = "relay unreachable: " + (e.message || e);
    this._list.appendChild(d);
  }

  _row(label, muted) {
    const row = document.createElement("div");
    row.style.cssText = "display:flex;align-items:center;gap:6px;font-size:.9rem;flex-wrap:wrap";
    const name = document.createElement("span");
    name.style.cssText = "flex:1;overflow:hidden;text-overflow:ellipsis;font-family:monospace;min-width:8rem";
    name.textContent = label;
    if (muted) name.style.color = "var(--secondary-text-color)";
    row.appendChild(name);
    return row;
  }
  _iconBtn(icon) {
    const b = document.createElement("button");
    b.style.cssText =
      "padding:2px 8px;border-radius:6px;border:1px solid var(--divider-color,#444);" +
      "background:var(--secondary-background-color,#1c2128);color:var(--primary-text-color);cursor:pointer;display:inline-flex;align-items:center";
    const i = document.createElement("ha-icon");
    i.setAttribute("icon", icon);
    i.style.cssText = "--mdc-icon-size:16px";
    b.appendChild(i);
    return b;
  }
  _btn(label) {
    const b = document.createElement("button");
    b.textContent = label;
    b.style.cssText =
      "padding:2px 10px;border-radius:6px;border:1px solid var(--divider-color,#444);" +
      "background:var(--secondary-background-color,#1c2128);color:var(--primary-text-color);cursor:pointer;font-size:.75rem";
    return b;
  }
  getCardSize() { return 3; }
}
customElements.define("vcast-screens-card", VcastScreensCard);
