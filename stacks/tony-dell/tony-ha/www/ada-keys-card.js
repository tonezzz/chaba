// ada-keys-card — lists issued Ada HA device keys with per-key actions.
// Same row layout as ada-users-card: name | bound badge | per-app open
// buttons (Voice/Text/View driven by the key's `apps` metadata, default
// voice+chat) | QR icon (re-pair popup via script.ada_pair_reissue
// return_response — inline svg + link + countdown + close) | Revoke.
// Reads the `issued`, `bindings`, and `apps` attributes of the
// ada_*_issued_keys rest sensors.
class AdaKeysCard extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._card = document.createElement("ha-card");
    this._card.header = config.title || "Issued keys";
    this._list = document.createElement("div");
    this._list.style.cssText = "padding:0 16px 16px;display:flex;flex-direction:column;gap:6px";
    this._card.appendChild(this._list);
    this.appendChild(this._card);
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _issued(inst) {
    const st = this._hass && this._hass.states["sensor.ada_" + inst.id + "_issued_keys"];
    return (st && st.attributes && st.attributes.issued) || [];
  }

  _keyAttrs(inst) {
    const st = this._hass && this._hass.states["sensor.ada_" + inst.id + "_issued_keys"];
    const attrs = (st && st.attributes) || {};
    return { bindings: attrs.bindings || {}, apps: attrs.apps || {} };
  }

  // Per-app open buttons for an issued key. apps = ["voice","chat","view"];
  // missing entry → the legacy voice+chat default.
  _appButtons(inst, key) {
    const { apps } = this._keyAttrs(inst);
    const list = apps[key] || ["voice", "chat"];
    const out = [];
    if (list.includes("voice")) {
      const voice = this._btn("Voice");
      voice.title = "Open the HA-native voice page for this instance (the card self-mints a key)";
      voice.onclick = () =>
        window.open(this._haUrl(inst.id), "_blank", "popup,width=1100,height=800");
      out.push(voice);
    }
    if (list.includes("chat")) {
      const chat = this._btn("Text");
      chat.title = "Open the HA-native chat page for this instance (the card self-mints a key)";
      chat.onclick = () =>
        window.open(this._haUrl(inst.id, "chat"), "_blank", "popup,width=1100,height=800");
      out.push(chat);
    }
    if (list.includes("view")) {
      const view = this._btn("View");
      view.title = "Mint a redeem link that lands this key on the cms viewer";
      view.onclick = () => this._repairAndOpen(inst.id, key, "cms");
      out.push(view);
    }
    return out;
  }

  _bindBadge(inst, key) {
    const { bindings } = this._keyAttrs(inst);
    const bound = bindings[key];
    const span = document.createElement("span");
    span.style.cssText = "font-size:.7rem;white-space:nowrap;color:" +
      (bound ? "var(--success-color,#3fb950)" : "var(--warning-color,#d29922)");
    span.textContent = bound === "*" ? "shared" : bound ? "bound" : "unbound";
    span.title = bound && bound !== "*" ? `bound to device ${bound}` :
      bound === "*" ? "shared key — device binding disabled" : "not bound to a device yet";
    return span;
  }

  _render() {
    const hass = this._hass;
    const list = this._list;
    if (!hass || !list) return;
    list.innerHTML = "";
    const insts = this._config.instances || [
      { id: "tony", title: "Tony", sensor: "sensor.ada_tony_issued_keys" },
      { id: "michael", title: "Michael", sensor: "sensor.ada_michael_issued_keys" },
    ];
    let any = false;
    for (const inst of insts) {
      const keys = this._issued(inst);
      if (!keys.length) continue;
      any = true;
      const head = document.createElement("div");
      head.style.cssText = "margin-top:6px;font-size:.8rem;color:var(--secondary-text-color);text-transform:uppercase;letter-spacing:.05em";
      head.textContent = inst.title;
      list.appendChild(head);
      for (const key of keys) {
        const row = document.createElement("div");
        row.style.cssText = "display:flex;align-items:center;gap:6px;font-size:.9rem";
        const name = document.createElement("span");
        name.style.cssText = "flex:1;overflow:hidden;text-overflow:ellipsis;font-family:monospace";
        name.textContent = key;
        const qr = this._iconBtn("mdi:qrcode");
        qr.title = "Re-pair — pop up a fresh pairing QR for this key";
        qr.onclick = () => this._showQrPopup(inst.id, key);
        const revoke = this._btn("Revoke");
        revoke.style.color = "var(--error-color, #f47067)";
        revoke.onclick = () => {
          if (confirm(`Revoke key "${key}" on ${inst.title}? The device loses access immediately.`))
            hass.callService("script", "ada_pair_revoke_named", { instance: inst.id, name: key });
        };
        row.append(name, this._bindBadge(inst, key), ...this._appButtons(inst, key), qr, revoke);
        list.appendChild(row);
      }
    }
    if (!any) {
      const empty = document.createElement("div");
      empty.style.color = "var(--secondary-text-color)";
      empty.textContent = "No issued keys.";
      list.appendChild(empty);
    }
  }

  async _showQrPopup(instance, name) {
    const ov = document.createElement("div");
    ov.style.cssText =
      "position:fixed;inset:0;z-index:9999;display:grid;place-items:center;background:rgba(0,0,0,.6)";
    const card = document.createElement("div");
    card.style.cssText =
      "background:var(--card-background-color,#1c2128);padding:20px;border-radius:12px;" +
      "display:flex;flex-direction:column;align-items:center;gap:10px;max-width:320px";
    const title = document.createElement("div");
    title.style.cssText = "font-weight:600;font-size:.95rem";
    title.textContent = `Pair ${name}`;
    const body = document.createElement("div");
    body.style.cssText =
      "width:232px;min-height:232px;background:#fff;border-radius:8px;padding:8px;" +
      "display:grid;place-items:center;color:#333;font-size:12px;text-align:center";
    body.textContent = "Minting QR…";
    const link = document.createElement("a");
    link.style.cssText = "font-size:.7rem;color:var(--primary-color);word-break:break-all;max-width:280px;cursor:pointer";
    link.rel = "noopener";
    const expiry = document.createElement("div");
    expiry.style.cssText = "font-size:.75rem;color:var(--secondary-text-color)";
    let timer = null;
    const done = () => { if (timer) clearInterval(timer); ov.remove(); };
    const close = this._btn("Close");
    close.onclick = done;
    ov.onclick = (e) => { if (e.target === ov) done(); };
    card.append(title, body, link, expiry, close);
    ov.appendChild(card);
    document.body.appendChild(ov);
    try {
      const res = await this._hass.callWS({
        type: "call_service",
        domain: "script",
        service: "ada_pair_reissue",
        service_data: { instance, name },
        return_response: true,
      });
      const content = res && res.response && res.response.content;
      const svg = content && content.qr_svg;
      const path = content && content.redeem_url;
      if (!svg || !path) throw new Error("no QR in response");
      body.innerHTML = svg;
      const svgEl = body.querySelector("svg");
      if (svgEl) {
        svgEl.setAttribute("width", "216");
        svgEl.setAttribute("height", "216");
      }
      // The link opens the HA web UI for this instance in a popup window —
      // HA is the primary Ada surface (the voice card self-mints keys), so
      // we don't send people to the standalone voice panel.
      const haUrl = this._haUrl(instance);
      link.onclick = (e) => {
        e.preventDefault();
        window.open(haUrl, "_blank", "popup,width=1100,height=800");
      };
      link.textContent = haUrl;
      let left = (content && content.expires_in) | 0 || 600;
      const tick = () => {
        expiry.textContent = left > 0
          ? `Single use — expires in ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`
          : "Expired — re-pair again for a fresh link.";
        left -= 1;
      };
      tick();
      timer = setInterval(tick, 1000);
    } catch (err) {
      body.textContent = "Re-pair failed: " + (err.message || err);
      body.style.color = "#b43228";
    }
  }

  // Mint a redeem link for an existing key and open it — the redeem endpoint
  // redirects to the app's path (e.g. /apps/ha/ada-tony/cms for ui="cms")
  // with the real key handed over via ?api_key=. Used by the View button.
  async _repairAndOpen(instance, name, ui) {
    try {
      const res = await this._hass.callWS({
        type: "call_service",
        domain: "script",
        service: "ada_pair_reissue",
        service_data: { instance, name, ui },
        return_response: true,
      });
      const content = res && res.response && res.response.content;
      const path = content && content.redeem_url;
      if (!path) throw new Error("no redeem url in response");
      window.open("https://mn01.taila0626a.ts.net" + path, "_blank", "popup,width=1100,height=800");
    } catch (err) {
      alert("Open failed: " + (err.message || err));
    }
  }

  _haUrl(instance, view) {
    if (this._config && this._config.ha_url) return this._config.ha_url;
    const map = {
      tony: `https://tony-dell.taila0626a.ts.net:8123/chaba-home/${view || "ai"}`,
      michael: "https://nupo4ndqdqydt78zmpq0z5wzp1bdrqgs.ui.nabu.casa/",
    };
    return map[instance] || map.tony;
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

  getCardSize() {
    return 3;
  }
}
customElements.define("ada-keys-card", AdaKeysCard);
