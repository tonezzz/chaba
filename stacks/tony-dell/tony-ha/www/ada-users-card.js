// ada-users-card — lists HA user accounts with per-user Ada pairing actions.
// Buttons: Issue (new keys, QR lands in ada-pair-qr-card), QR icon (re-pair —
// pops up a fresh pairing QR in place), Revoke.
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
        const qr = this._iconBtn("mdi:qrcode");
        qr.title = "Re-pair — pop up a fresh pairing QR for this key";
        qr.onclick = () => this._showQrPopup(inst, key);
        const revoke = this._btn("Revoke");
        revoke.style.color = "var(--error-color, #f47067)";
        revoke.onclick = () => {
          if (confirm(`Revoke key "${key}" on ${inst}? The device loses access immediately.`))
            hass.callService("script", "ada_pair_revoke_named", { instance: inst, name: key });
        };
        row.append(qr, revoke);
      }
      list.appendChild(row);
    }
    this._renderPendingGuests(list);
  }

  // Pending chaba guest registrations — fed by sensor.chaba_pending_guests
  // (a REST sensor polling the chaba guest service). Promote/dismiss run
  // script.chaba_guest_promote / script.chaba_guest_revoke on the live host.
  _renderPendingGuests(list) {
    const hass = this._hass;
    const st = hass && hass.states["sensor.chaba_pending_guests"];
    const pending = (st && st.attributes && st.attributes.pending) || [];
    const head = document.createElement("div");
    head.style.cssText = "margin-top:10px;font-size:.8rem;color:var(--secondary-text-color);text-transform:uppercase;letter-spacing:.05em";
    head.textContent = `Pending guests (${pending.length})`;
    list.appendChild(head);
    if (!pending.length) {
      const none = document.createElement("div");
      none.style.cssText = "font-size:.85rem;color:var(--secondary-text-color)";
      none.textContent = st ? "No pending registrations." : "sensor.chaba_pending_guests unavailable";
      list.appendChild(none);
      return;
    }
    for (const g of pending) {
      const row = document.createElement("div");
      row.style.cssText = "display:flex;align-items:center;gap:6px;font-size:.9rem";
      const name = document.createElement("span");
      name.style.cssText = "flex:1;overflow:hidden;text-overflow:ellipsis";
      name.textContent = g.name + (g.requested_at ? ` — ${String(g.requested_at).slice(0, 16)}` : "");
      const promote = this._btn("Promote");
      promote.title = `Promote ${g.name} to a named user (creates person.<name>, binds voiceprint, opens private namespace)`;
      promote.onclick = () => hass.callService("script", "chaba_guest_promote", { name: g.name });
      const dismiss = this._btn("Dismiss");
      dismiss.style.color = "var(--error-color, #f47067)";
      dismiss.onclick = () => {
        if (confirm(`Dismiss pending guest "${g.name}"?`))
          hass.callService("script", "chaba_guest_revoke", { name: g.name });
      };
      row.append(name, promote, dismiss);
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
    link.style.cssText = "font-size:.7rem;color:var(--primary-color);word-break:break-all;max-width:280px";
    link.target = "_blank";
    link.rel = "noopener";
    const close = this._btn("Close");
    close.onclick = () => ov.remove();
    ov.onclick = (e) => { if (e.target === ov) ov.remove(); };
    card.append(title, body, link, close);
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
      const url = ((this._config && this._config.origin) || "https://mn01.taila0626a.ts.net") + path;
      link.href = url;
      link.textContent = url;
    } catch (err) {
      body.textContent = "Re-pair failed: " + (err.message || err);
      body.style.color = "#b43228";
    }
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
    return 4;
  }
}
customElements.define("ada-users-card", AdaUsersCard);
