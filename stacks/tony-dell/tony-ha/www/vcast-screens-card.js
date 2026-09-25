// vcast-screens-card — lists virtual cast displays registered on the
// input-bridge relay, plus pending (unpaired) displays showing a QR.
// Polls GET <api>/displays; actions: test-cast (nav/play/audio pub), re-pair
// (push unpaired -> display shows its QR again), release (revoke key).
// "Add screen" pops a QR for the bare /apps/vcast/ URL — scan it on the
// device to open the app; the device then shows its own claim QR.
// Config: api (default https://tony-dell.taila0626a.ts.net/api/input-bridge),
//         refresh (seconds, default 5), test_play_url, test_nav_url,
//         test_audio_url, app_url
class VcastScreensCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._api = (this._config.api || "https://tony-dell.taila0626a.ts.net/api/input-bridge").replace(/\/+$/, "");
    this._origin = this._api.replace(/\/api\/input-bridge\/?$/, "");
    this._appUrl = this._config.app_url || `${this._origin}/apps/vcast/`;
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

  async _qrLib() {
    if (window.qrcode) return window.qrcode;
    if (!this._qrP) {
      this._qrP = new Promise((res, rej) => {
        const s = document.createElement("script");
        s.src = "/local/qrcode.min.js";
        s.onload = () => res(window.qrcode);
        s.onerror = () => rej(new Error("qrcode.min.js not found"));
        document.head.appendChild(s);
      });
    }
    return this._qrP;
  }

  async _showAppQr() {
    const ov = document.createElement("div");
    ov.style.cssText =
      "position:fixed;inset:0;z-index:9999;display:grid;place-items:center;background:rgba(0,0,0,.6)";
    const card = document.createElement("div");
    card.style.cssText =
      "background:var(--card-background-color,#1c2128);padding:20px;border-radius:12px;" +
      "display:flex;flex-direction:column;align-items:center;gap:10px;max-width:340px";
    const title = document.createElement("div");
    title.style.cssText = "font-weight:600;font-size:.95rem";
    title.textContent = "Open vcast on a device";
    const body = document.createElement("div");
    body.style.cssText =
      "width:236px;min-height:236px;background:#fff;border-radius:8px;padding:8px;" +
      "display:grid;place-items:center;color:#333;font-size:12px;text-align:center";
    body.textContent = "rendering…";
    const link = document.createElement("a");
    link.style.cssText = "font-size:.7rem;color:var(--primary-color);word-break:break-all;max-width:300px";
    link.href = this._appUrl;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = this._appUrl;
    const hint = document.createElement("div");
    hint.style.cssText = "font-size:.72rem;color:var(--secondary-text-color);text-align:center";
    hint.textContent = "The device opens unpaired and shows its own QR — scan that to claim it.";
    const close = this._btn("Close");
    close.onclick = () => ov.remove();
    ov.onclick = (e) => { if (e.target === ov) ov.remove(); };
    card.append(title, body, link, hint, close);
    ov.appendChild(card);
    document.body.appendChild(ov);
    try {
      const qrlib = await this._qrLib();
      const qr = qrlib(0, "M");
      qr.addData(this._appUrl);
      qr.make();
      body.innerHTML = qr.createImgTag(5);
    } catch (e) {
      body.textContent = "QR failed — open " + this._appUrl;
      body.style.color = "#b43228";
    }
  }

  _render(data) {
    const list = this._list;
    list.innerHTML = "";
    const screens = (data && data.screens) || [];
    const pending = (data && data.pending) || [];

    const top = document.createElement("div");
    top.style.cssText = "display:flex;align-items:center;gap:8px";
    const hintEl = document.createElement("span");
    hintEl.style.cssText = "flex:1;font-size:.75rem;color:var(--secondary-text-color)";
    hintEl.textContent = "New display:";
    const addBtn = this._btn("➕ QR");
    addBtn.title = "Show a QR that opens /apps/vcast/ on a device (it then shows its own claim QR)";
    addBtn.onclick = () => this._showAppQr();
    top.append(hintEl, addBtn);
    list.appendChild(top);

    if (!screens.length && !pending.length) {
      const d = document.createElement("div");
      d.style.color = "var(--secondary-text-color)";
      d.innerHTML = "No screens yet — scan the QR above to open <b>/apps/vcast/</b> on a device.";
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
      const sndBtn = this._iconBtn("mdi:volume-high");
      sndBtn.title = "Play a test sound (needs the 'tap for audio' gesture once on iOS)";
      sndBtn.onclick = async () => {
        const r = await this._pub(s.screen, {
          type: "audio",
          url: this._config.test_audio_url || `${this._origin}/apps/vcast/beep.wav`,
        });
        sndBtn.style.opacity = r.delivered ? "0.5" : "1";
        setTimeout(() => (sndBtn.style.opacity = "1"), 1200);
      };
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
      row.append(playBtn, navBtn, sndBtn, stopBtn, reBtn, del);
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
