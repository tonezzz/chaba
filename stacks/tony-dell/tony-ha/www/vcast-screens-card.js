// vcast-screens-card — lists virtual cast displays registered on the
// input-bridge relay, plus pending (unpaired) displays showing a QR.
// Polls GET <api>/displays; actions: test-cast (nav/play/audio pub), re-pair
// (push unpaired -> display shows its QR again), release (revoke key).
// "Add screen" pops a QR for the bare /apps/vcast/ URL — scan it on the
// device to open the app; the device then shows its own claim QR.
// Config: api (default https://idc02.taila0626a.ts.net/api/input-bridge),
//         refresh (seconds, default 5), test_play_url, test_nav_url,
//         test_audio_url, app_url
class VcastScreensCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._api = (this._config.api || "https://idc02.taila0626a.ts.net/api/input-bridge").replace(/\/+$/, "");
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
    const urls = [
      { label: "Tailnet (recommended)", url: this._appUrl },
      { label: "Home Wi-Fi (no VPN)", url: this._config.lan_url || "http://192.168.2.67/apps/vcast/" },
    ];
    let qrlib = null;
    try { qrlib = await this._qrLib(); } catch (e) {}

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
    const tabs = document.createElement("div");
    tabs.style.cssText = "display:flex;gap:6px";
    const body = document.createElement("div");
    body.style.cssText =
      "width:236px;min-height:236px;background:#fff;border-radius:8px;padding:8px;" +
      "display:grid;place-items:center;color:#333;font-size:12px;text-align:center";
    const link = document.createElement("a");
    link.style.cssText = "font-size:.7rem;color:var(--primary-color);word-break:break-all;max-width:300px";
    link.target = "_blank"; link.rel = "noopener";
    const hint = document.createElement("div");
    hint.style.cssText = "font-size:.72rem;color:var(--secondary-text-color);text-align:center";
    const close = this._btn("Close");
    close.onclick = () => ov.remove();
    ov.onclick = (e) => { if (e.target === ov) ov.remove(); };

    const pick = (i, btn) => {
      for (const b of tabs.children) b.style.fontWeight = "400";
      btn.style.fontWeight = "700";
      const u = urls[i].url;
      link.href = u; link.textContent = u;
      if (qrlib) {
        const qr = qrlib(0, "M");
        qr.addData(u); qr.make();
        body.innerHTML = qr.createImgTag(5);
      } else {
        body.textContent = u;
      }
      hint.textContent = i === 0
        ? "iPad/iPhone must have Tailscale VPN connected — otherwise Safari can't open it."
        : "Works on the same Wi-Fi, no Tailscale. Device opens unpaired and shows its own claim QR.";
    };
    urls.forEach((u, i) => {
      const b = this._btn(u.label);
      b.onclick = () => pick(i, b);
      tabs.appendChild(b);
    });
    card.append(title, tabs, body, link, hint, close);
    ov.appendChild(card);
    document.body.appendChild(ov);
    pick(0, tabs.children[0]);
  }

  _age(s) {
    if (s == null) return "";
    return s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)}m` : `${Math.floor(s / 3600)}h`;
  }
  _lifecycle(s) {
    // derived server-side since the ux-flow rework; fall back to the
    // connected flag on older relays
    const lc = s.lifecycle || (s.connected ? "connected" : "stale");
    const color = { playing: "var(--primary-color)", idle: "#4caf50",
      connected: "#4caf50", pairing: "var(--secondary-text-color)",
      reconnecting: "var(--warning-color,#f59e0b)",
      stale: "var(--error-color,#f47067)" }[lc] || "var(--secondary-text-color)";
    const age = s.age_s != null ? ` ${this._age(s.age_s)}` : "";
    const extra = lc === "reconnecting" && s.reclaim_in_s != null
      ? ` · frees ~${s.reclaim_in_s}s` : "";
    const detail = lc === "playing" && s.lifecycle_detail
      ? ` · ${s.lifecycle_detail}` : "";
    return `<span style="color:${color};font-weight:600">${lc}${age}</span>${extra}${detail}`;
  }

  _render(data) {
    const list = this._list;
    list.innerHTML = "";
    const screens = (data && data.screens) || [];
    const pending = (data && data.pending) || [];
    const h = (data && data.health) || null;

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

    // fleet health line — connected/stale/pending + flap metric surfaced
    // from the relay (vcast-auto-health counts the same events)
    if (h) {
      const fh = document.createElement("div");
      fh.style.cssText = "font-size:.72rem;color:var(--secondary-text-color)";
      fh.innerHTML =
        `<b>${h.connected ?? 0}</b> connected · ` +
        `<b>${h.reconnecting ?? 0}</b> reconnecting · ` +
        `<b>${h.stale ?? 0}</b> stale · ` +
        `<b>${h.pending ?? pending.length}</b> pairing · ` +
        `<b>${h.released ?? 0}</b> released — ` +
        `flaps 24h: <b>${h.flaps_24h ?? "?"}</b>` +
        (h.last_flap ? ` · last ${this._relTime(h.last_flap)}` : "");
      list.appendChild(fh);
    }

    if (!screens.length && !pending.length) {
      const d = document.createElement("div");
      d.style.color = "var(--secondary-text-color)";
      d.innerHTML = "No screens yet — scan the QR above to open <b>/apps/vcast/</b> on a device.";
      list.appendChild(d);
      return;
    }

    for (const p of pending) {
      const code = p.code ? ` · code ${p.code}` : "";
      const exp = p.expires_in_s != null ? ` · expires ${this._age(p.expires_in_s)}` : "";
      const row = this._row(
        `⏳ ${p.label || "display"} — waiting to pair${code}${exp}`, true);
      const open = this._btn("Pair");
      open.title = "Open the claim page (same flow the on-screen QR starts)";
      open.onclick = () => {
        const base = new URL(this._appUrl).origin;
        window.open(`${base}/apps/vcast/pair.html?sid=${encodeURIComponent(p.sid)}`, "_blank");
      };
      const dis = this._btn("Dismiss");
      dis.title = "Drop this pending display without pairing";
      dis.onclick = async () => {
        const r = await this._call("/dismiss", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ sid: p.sid }),
        });
        if (r.error) alert("Dismiss failed: " + r.error + (r.next ? "\n→ " + r.next : ""));
        this._poll();
      };
      row.append(open, dis);
      list.appendChild(row);
    }

    for (const s of screens) {
      // label is the primary identity; name + drift as secondary detail
      const row = this._row(`#${s.screen} ${s.label || s.name}`, false);
      if (s.label_dup) row.firstChild.style.color = "var(--error-color,#f47067)";
      const meta = document.createElement("span");
      meta.style.cssText = "font-size:.7rem;color:var(--secondary-text-color);white-space:nowrap";
      const drift = s.drift ? ` (→${s.preferred_screen})` : "";
      meta.innerHTML = `${s.name}${drift} · ${this._lifecycle(s)}`;
      row.appendChild(meta);

      const playBtn = this._btn("▶");
      playBtn.title = "Cast test HLS stream";
      playBtn.onclick = async () => {
        const r = await this._pub(s.screen, {
          type: "play",
          url: this._config.test_play_url || "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8",
        });
        playBtn.textContent = r.delivered ? "✓" : "!";
        playBtn.title = r.delivered
          ? "cast delivered" : "NOT delivered — no live socket on that screen";
        setTimeout(() => (playBtn.textContent = "▶"), 1500);
      };
      const navBtn = this._iconBtn("mdi:open-in-app");
      navBtn.title = "Cast a test page (iframe nav)";
      navBtn.onclick = () =>
        this._pub(s.screen, { type: "nav", url: this._config.test_nav_url || "https://idc02.taila0626a.ts.net/apps/" });
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
      row.append(playBtn, navBtn, sndBtn, stopBtn);
      if (s.connected) {
        const reBtn = this._iconBtn("mdi:qrcode");
        reBtn.title = "Re-pair — display drops its key and shows the claim QR again";
        reBtn.onclick = () => this._pub(s.screen, { type: "unpaired" });
        row.appendChild(reBtn);
      } else {
        const sw = this._btn("Sweep");
        sw.title = "Free the name+slot now — the one-click fix for a dead-socket hold";
        sw.onclick = async () => {
          const r = await this._call("/sweep", {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ screen: s.screen }),
          });
          if (r.error) alert("Sweep failed: " + r.error + (r.next ? "\n→ " + r.next : ""));
          this._poll();
        };
        row.appendChild(sw);
      }
      const del = this._btn("Release");
      del.style.color = "var(--error-color,#f47067)";
      del.onclick = async () => {
        if (!confirm(`Release ${s.name}? The name is tombstoned (reserved 30d for reclaim).`)) return;
        const r = await this._call("/release", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ screen: s.screen }),
        });
        if (r.error) alert("Release failed: " + r.error + (r.next ? "\n→ " + r.next : ""));
        else if (r.note) this._note(r.note);
        this._poll();
      };
      row.appendChild(del);
      list.appendChild(row);
    }

    // released tombstones — names reserved for reclaim, informational
    for (const t of (data.released || []).slice(0, 4)) {
      const row = this._row(
        `🪦 ${t.name} — released · reserved until ${String(t.reclaim_until || "").slice(0, 10)}`, true);
      list.appendChild(row);
    }
  }

  _relTime(iso) {
    const s = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000));
    return this._age(s) + " ago";
  }
  _note(text) {
    // transient confirmation line at the top of the card — the visible
    // result the release/reclaim flows were missing
    const d = document.createElement("div");
    d.style.cssText = "font-size:.75rem;color:var(--primary-color)";
    d.textContent = text;
    this._list.prepend(d);
    setTimeout(() => d.remove(), 6000);
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
