// ada-keys-card — lists issued Ada HA device keys with per-key Re-pair/Revoke.
// Reads the `issued` attribute of the ada_*_issued_keys rest sensors and calls
// the field-based scripts script.ada_pair_reissue / script.ada_pair_revoke_named.
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
    const insts = this._config.instances || [
      { id: "tony", title: "Tony", sensor: "sensor.ada_tony_issued_keys" },
      { id: "michael", title: "Michael", sensor: "sensor.ada_michael_issued_keys" },
    ];
    const list = this._list;
    list.innerHTML = "";
    let any = false;
    for (const inst of insts) {
      const st = hass.states[inst.sensor];
      const keys = (st && st.attributes && st.attributes.issued) || [];
      if (!keys.length) continue;
      any = true;
      const head = document.createElement("div");
      head.style.cssText = "font-weight:500;margin-top:6px";
      head.textContent = inst.title;
      list.appendChild(head);
      for (const key of keys) {
        const row = document.createElement("div");
        row.style.cssText = "display:flex;align-items:center;gap:8px;font-size:.9rem";
        const code = document.createElement("a");
        code.href = "#";
        code.title = "Re-pair and open the session in this browser (admin verify)";
        code.style.cssText = "flex:1;color:var(--primary-color);text-decoration:none;font-family:monospace";
        code.textContent = key;
        code.onclick = (e) => this._repairAndOpen(e, inst.id, key, code);
        const repair = this._btn("Re-pair");
        repair.onclick = () =>
          hass.callService("script", "ada_pair_reissue", { instance: inst.id, name: key });
        const revoke = this._btn("Revoke");
        revoke.style.color = "var(--error-color, #f47067)";
        revoke.onclick = () => {
          if (confirm(`Revoke key "${key}" on ${inst.title}? The device loses access immediately.`))
            hass.callService("script", "ada_pair_revoke_named", { instance: inst.id, name: key });
        };
        row.append(code, repair, revoke);
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

  async _repairAndOpen(e, instance, name, el) {
    e.preventDefault();
    if (el.dataset.busy) return;
    el.dataset.busy = "1";
    const prev = el.textContent;
    el.textContent = name + " — re-pairing…";
    // Open the window synchronously inside the user gesture — iOS Safari and
    // webviews block window.open calls that happen after an await.
    const win = window.open("", "_blank");
    try {
      const res = await this._hass.callWS({
        type: "call_service",
        domain: "script",
        service: "ada_pair_reissue",
        service_data: { instance, name },
        return_response: true,
      });
      const path = res && res.response && res.response.content && res.response.content.redeem_url;
      if (!path) throw new Error("no redeem_url in response");
      const url = ((this._config && this._config.origin) || "https://mn01.taila0626a.ts.net") + path;
      if (win) {
        win.location.href = url;
      } else {
        this._showOpenLink(el, url, name);   // popup fully blocked → inline link
        return;
      }
    } catch (err) {
      if (win) win.close();
      el.textContent = name + " — failed: " + (err.message || err);
      setTimeout(() => { el.textContent = prev; delete el.dataset.busy; }, 4000);
      return;
    }
    el.textContent = prev;
    delete el.dataset.busy;
  }

  _showOpenLink(el, url, name) {
    el.textContent = "";
    const a = document.createElement("a");
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener";
    a.style.color = "var(--primary-color)";
    a.textContent = "Tap to open session";
    a.onclick = () => { setTimeout(() => { el.textContent = name; }, 500); };
    el.appendChild(a);
    setTimeout(() => { if (el.contains(a)) el.textContent = name; }, 120000);
    delete el.dataset.busy;
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
