// ada-users-card — lists HA user accounts with per-user Ada pairing actions.
// Same button vocabulary as ada-keys-card (Voice/Text/Re-pair/Revoke) plus an
// Issue action that drives script.ada_pair_issue via the shared inputs so the
// pairing QR lands in the ada-pair-qr-card on this view.
// Per-user Ada key name convention: user-<username>.
class AdaUsersCard extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._card = document.createElement("ha-card");
    this._card.header = config.title || "HA users";
    this._list = document.createElement("div");
    this._list.style.cssText = "padding:0 16px 16px;display:flex;flex-direction:column;gap:6px";
    this._card.appendChild(this._list);
    this.appendChild(this._card);
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._users) this._load();
    this._render();
  }

  async _load() {
    try {
      const res = await this._hass.callWS({ type: "config/auth/list" });
      this._users = (res || []).filter((u) => !u.system_generated);
    } catch (e) {
      this._users = [];
      this._loadError = e.message || String(e);
    }
    this._render();
  }

  _keyName(u) {
    const base = (u.username || u.name || "").toLowerCase().split("@")[0].replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
    return "user-" + (base || "unnamed");
  }

  _instance() {
    const sel = this._hass && this._hass.states["input_select.ada_pair_instance"];
    return (sel && sel.state) || (this._config && this._config.instance) || "tony";
  }

  _issued(inst) {
    const st = this._hass && this._hass.states["sensor.ada_" + inst + "_issued_keys"];
    return new Set((st && st.attributes && st.attributes.issued) || []);
  }

  _render() {
    const hass = this._hass;
    const list = this._list;
    if (!hass || !list) return;
    list.innerHTML = "";
    if (this._loadError) {
      const e = document.createElement("div");
      e.style.color = "var(--error-color,#f47067)";
      e.textContent = "Could not list users: " + this._loadError;
      list.appendChild(e);
      return;
    }
    if (!this._users) {
      const l = document.createElement("div");
      l.style.color = "var(--secondary-text-color)";
      l.textContent = "Loading users…";
      list.appendChild(l);
      return;
    }
    if (!this._users.length) {
      const e = document.createElement("div");
      e.style.color = "var(--secondary-text-color)";
      e.textContent = "No users.";
      list.appendChild(e);
      return;
    }
    const inst = this._instance();
    const issued = this._issued(inst);
    for (const u of this._users) {
      const key = this._keyName(u);
      const hasKey = issued.has(key);
      const row = document.createElement("div");
      row.style.cssText = "display:flex;align-items:center;gap:6px;font-size:.9rem";
      const name = document.createElement("span");
      name.style.cssText = "flex:1;overflow:hidden;text-overflow:ellipsis";
      name.textContent = u.name + (u.username ? " (" + u.username + ")" : "");
      const badges = document.createElement("span");
      badges.style.cssText = "font-size:.7rem;color:var(--secondary-text-color);white-space:nowrap";
      const flags = [];
      if (u.is_owner) flags.push("owner");
      if (u.local_only) flags.push("local");
      if (!u.is_active) flags.push("inactive");
      badges.textContent = flags.join(" ");
      const code = document.createElement("span");
      code.style.cssText = "font-family:monospace;font-size:.75rem;color:var(--secondary-text-color)";
      code.textContent = key;
      row.append(name, badges, code);
      if (!hasKey) {
        const issue = this._btn("Issue");
        issue.title = `Issue key "${key}" on ${inst} — sets the shared inputs and generates a pairing QR below`;
        issue.onclick = () => this._issue(code, inst, key);
        row.appendChild(issue);
      } else {
        const voice = this._btn("Voice");
        voice.title = "Re-pair and open the voice interface in a popup";
        voice.onclick = (e) => this._repairAndOpen(e, inst, key, code, "voice");
        const chat = this._btn("Text");
        chat.title = "Re-pair and open the text chat interface in a popup";
        chat.onclick = (e) => this._repairAndOpen(e, inst, key, code, "chat");
        const repair = this._btn("Re-pair");
        repair.title = "Re-pair without opening — refreshes the QR on this dashboard";
        repair.onclick = () => hass.callService("script", "ada_pair_reissue", { instance: inst, name: key });
        const revoke = this._btn("Revoke");
        revoke.style.color = "var(--error-color, #f47067)";
        revoke.onclick = () => {
          if (confirm(`Revoke key "${key}" on ${inst}? The device loses access immediately.`))
            hass.callService("script", "ada_pair_revoke_named", { instance: inst, name: key });
        };
        row.append(voice, chat, repair, revoke);
      }
      list.appendChild(row);
    }
  }

  async _issue(el, instance, key) {
    if (el.dataset.busy) return;
    el.dataset.busy = "1";
    const prev = el.textContent;
    el.textContent = key + " — issuing…";
    try {
      // Point the shared pair inputs at this user, then run the normal issue
      // script so the QR + redeem url land in the existing pair cards.
      await this._hass.callService("input_select", "select_option", {
        entity_id: "input_select.ada_pair_instance",
        option: instance,
      });
      await this._hass.callService("input_text", "set_value", {
        entity_id: "input_text.ada_pair_device_name",
        value: key,
      });
      await this._hass.callService("script", "ada_pair_issue", {});
    } catch (err) {
      el.textContent = key + " — failed: " + (err.message || err);
      setTimeout(() => { el.textContent = prev; delete el.dataset.busy; }, 4000);
      return;
    }
    el.textContent = key + " — QR below";
    setTimeout(() => { el.textContent = prev; delete el.dataset.busy; }, 6000);
  }

  async _repairAndOpen(e, instance, name, el, ui) {
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
        service_data: { instance, name, ui },
        return_response: true,
      });
      const path = res && res.response && res.response.content && res.response.content.redeem_url;
      if (!path) throw new Error("no redeem_url in response");
      const url = ((this._config && this._config.origin) || "https://mn01.taila0626a.ts.net") + path;
      if (win) {
        win.location.href = url;
      } else {
        this._showOpenLink(el, url, name);
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
    return 4;
  }
}
customElements.define("ada-users-card", AdaUsersCard);
