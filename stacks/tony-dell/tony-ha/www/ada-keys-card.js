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
        row.style.cssText = "display:flex;align-items:center;gap:6px;font-size:.9rem";
        const code = document.createElement("span");
        code.style.cssText = "flex:1;font-family:monospace;overflow:hidden;text-overflow:ellipsis";
        code.textContent = key;
        const voice = this._btn("Voice");
        voice.title = "Open the HA-native voice page for this instance (the card self-mints a key)";
        voice.onclick = () =>
          window.open(this._haUrl(inst.id), "_blank", "popup,width=1100,height=800");
        const chat = this._btn("Text");
        chat.title = "Open the HA-native chat page for this instance (the card self-mints a key)";
        chat.onclick = () =>
          window.open(this._haUrl(inst.id, "chat"), "_blank", "popup,width=1100,height=800");
        const repair = this._btn("Re-pair");
        repair.title = "Re-pair without opening — refreshes the QR on this dashboard";
        repair.onclick = () =>
          hass.callService("script", "ada_pair_reissue", { instance: inst.id, name: key });
        const revoke = this._btn("Revoke");
        revoke.style.color = "var(--error-color, #f47067)";
        revoke.onclick = () => {
          if (confirm(`Revoke key "${key}" on ${inst.title}? The device loses access immediately.`))
            hass.callService("script", "ada_pair_revoke_named", { instance: inst.id, name: key });
        };
        row.append(code, voice, chat, repair, revoke);
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

  _haUrl(instance, view) {
    if (this._config && this._config.ha_url) return this._config.ha_url;
    const map = {
      tony: `https://tony-dell.taila0626a.ts.net:8123/chaba-home/${view || "ai"}`,
      michael: "https://nupo4ndqdqydt78zmpq0z5wzp1bdrqgs.ui.nabu.casa/",
    };
    return map[instance] || map.tony;
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
