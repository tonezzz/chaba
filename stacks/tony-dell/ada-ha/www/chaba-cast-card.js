/* chaba-cast-card — pick a yt-cached video, cast to a media_player.
 *
 * Browses HA media_source collections (yt_live / yt_cache / yt_corpus),
 * casts via media_player.play_media with the LAN URL on tony-dell's web
 * stack (Chromecasts fetch http://192.168.2.67/apps/<lane>/<path> over LAN —
 * they cannot reach ada-ha's loopback/tailnet bind).
 *
 * Config:
 *   type: custom:chaba-cast-card
 *   title: Cast to screen        (optional)
 *   collections: [yt_live, yt_cache, yt_corpus]   (optional)
 *   player: media_player.tony_tv_cast           (optional default)
 */
class ChabaCastCard extends HTMLElement {
  static getStubConfig() { return { collections: ["yt_live", "yt_cache"] }; }

  setConfig(config) {
    this._config = config || {};
    this._collection = this._collections()[0];
    this._files = [];      // {label, path} path = relpath under collection root
    this._loading = false;
    if (this._hass) this._render(), this._load();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) { this._render(); this._load(); }
    else this._refreshPlayers();
  }

  _collections() {
    const c = this._config.collections;
    return Array.isArray(c) && c.length ? c : ["yt_live", "yt_cache", "yt_corpus"];
  }

  _lanBase(col) { return `http://192.168.2.67/apps/${col.replace(/_/g, "-")}/`; }

  _players() {
    if (!this._hass) return [];
    return Object.keys(this._hass.states)
      .filter(e => e.startsWith("media_player."))
      .sort((a, b) => (a === "media_player.tony_tv_cast" ? -1 : b === "media_player.tony_tv_cast" ? 1 : a.localeCompare(b)));
  }

  async _browse(mid) {
    const r = await this._hass.callWS({
      type: "media_source/browse_media", media_content_id: mid });
    return (r && r.children) || [];
  }

  async _load() {
    if (!this._hass || this._loading) return;
    this._loading = true;
    this._status(`Loading ${this._collection}…`);
    const files = [];
    try {
      const root = `media-source://media_source/${this._collection}`;
      const kids = await this._browse(root);
      for (const k of kids) {
        if (k.can_expand) {
          for (const f of await this._browse(k.media_content_id)) {
            files.push({ label: `${k.title} · ${f.title}`,
                         path: String(f.media_content_id).replace(root + "/", "") });
          }
        } else {
          files.push({ label: k.title,
                       path: String(k.media_content_id).replace(root + "/", "") });
        }
      }
      this._files = files.filter(f => /\.(mp4|m4v|webm|mkv|mp3|m4a)$/i.test(f.path));
      this._status(this._files.length ? "" : `No media files in ${this._collection}`);
    } catch (e) {
      this._status(`Browse failed: ${e.message || e}`);
    }
    this._loading = false;
    this._renderList();
  }

  _status(t) { if (this._statusEl) this._statusEl.textContent = t; }

  async _cast(path) {
    const player = this._playerSel && this._playerSel.value;
    if (!player) { this._status("Pick a screen first"); return; }
    const url = this._lanBase(this._collection) + path;
    this._status(`Casting ${path} → ${player}`);
    try {
      await this._hass.callService("media_player", "play_media", {
        entity_id: player, media_content_id: url, media_content_type: "video/mp4" });
      this._status(`Playing on ${player.split(".")[1]}`);
    } catch (e) {
      this._status(`Cast failed: ${e.message || e}`);
    }
  }

  _render() {
    if (this._built) return;
    this._built = true;
    const fs = Number(this._config.font_scale) || 1.1;
    const card = document.createElement("ha-card");
    card.innerHTML = `<div style="padding:12px 16px 4px;font-size:${1.05*fs}rem;font-weight:600">${this._config.title || "Cast media"}</div>`;
    const body = document.createElement("div");
    body.style.cssText = "padding:0 12px 14px;display:flex;flex-direction:column;gap:8px";

    // row: collection tabs + player dropdown
    const row = document.createElement("div");
    row.style.cssText = "display:flex;gap:8px;flex-wrap:wrap;align-items:center";
    this._collections().forEach(col => {
      const b = document.createElement("button");
      b.textContent = col;
      b.style.cssText = `min-height:44px;padding:8px 14px;border-radius:8px;border:1px solid var(--divider-color,#444);background:var(--secondary-background-color,#1c2128);color:var(--primary-text-color);cursor:pointer;font-size:${0.85*fs}rem`;
      b.onclick = () => { this._collection = col; this._load(); };
      row.appendChild(b);
    });
    this._playerSel = document.createElement("select");
    this._playerSel.style.cssText = `min-height:44px;flex:1;min-width:140px;border-radius:8px;border:1px solid var(--divider-color,#444);background:var(--secondary-background-color,#1c2128);color:var(--primary-text-color);font-size:${0.85*fs}rem;padding:0 8px`;
    row.appendChild(this._playerSel);
    body.appendChild(row);

    this._statusEl = document.createElement("div");
    this._statusEl.style.cssText = `font-size:${0.8*fs}rem;color:var(--secondary-text-color);min-height:1.2em`;
    body.appendChild(this._statusEl);

    this._listEl = document.createElement("div");
    this._listEl.style.cssText = "display:flex;flex-direction:column;gap:6px;max-height:340px;overflow-y:auto";
    body.appendChild(this._listEl);

    card.appendChild(body);
    this.appendChild(card);
    this._refreshPlayers();
  }

  _refreshPlayers() {
    if (!this._playerSel) return;
    const cur = this._playerSel.value;
    this._playerSel.innerHTML = "";
    for (const p of this._players()) {
      const o = document.createElement("option");
      o.value = p;
      o.textContent = (this._hass.states[p].attributes.friendly_name || p).slice(0, 40);
      this._playerSel.appendChild(o);
    }
    const want = this._config.player || cur || "media_player.tony_tv_cast";
    if ([...this._playerSel.options].some(o => o.value === want)) this._playerSel.value = want;
  }

  _renderList() {
    if (!this._listEl) return;
    this._listEl.innerHTML = "";
    for (const f of this._files) {
      const b = document.createElement("button");
      b.textContent = "▶ " + f.label;
      b.style.cssText = "min-height:44px;text-align:left;padding:8px 12px;border-radius:8px;border:1px solid var(--divider-color,#444);background:var(--secondary-background-color,#1c2128);color:var(--primary-text-color);cursor:pointer;font-size:0.95rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis";
      b.onclick = () => this._cast(f.path);
      this._listEl.appendChild(b);
    }
  }
}

customElements.define("chaba-cast-card", ChabaCastCard);
