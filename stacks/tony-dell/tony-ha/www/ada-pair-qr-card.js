// ada-pair-qr-card — shows the latest Ada HA pairing QR + redeem link.
// Reads input_text.ada_pair_redeem_url and renders /local/pair-qr.svg with a
// ?v= param derived from the redeem token so each new issue busts the cache.
class AdaPairQrCard extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._card = document.createElement("ha-card");
    this._card.header = config.title || "Pairing QR";
    this._body = document.createElement("div");
    this._body.style.cssText =
      "padding:0 16px 16px;display:flex;flex-direction:column;align-items:center;gap:10px";
    this._card.appendChild(this._body);
    this.appendChild(this._card);
  }

  set hass(hass) {
    const url = (hass.states["input_text.ada_pair_redeem_url"] || {}).state || "";
    if (url === this._lastUrl) return;   // no change — don't rebuild the <img>
    this._lastUrl = url;
    const body = this._body;
    body.innerHTML = "";
    if (!url || url === "unknown" || url === "unavailable") {
      const d = document.createElement("div");
      d.style.cssText = "color:var(--secondary-text-color);padding:24px 0";
      d.textContent = "No pairing link yet — generate or re-pair a key.";
      body.appendChild(d);
      return;
    }
    const v = url.split("/").pop() || Date.now();
    const img = document.createElement("img");
    img.src = "/local/pair-qr.svg?v=" + encodeURIComponent(v);
    img.alt = "Pairing QR";
    img.style.cssText = "width:220px;height:220px;background:#fff;border-radius:8px;padding:8px";
    body.appendChild(img);
    const link = document.createElement("div");
    link.style.cssText =
      "font-size:.75rem;color:var(--secondary-text-color);word-break:break-all;text-align:center;user-select:text";
    link.textContent = url;
    body.appendChild(link);
    const hint = document.createElement("div");
    hint.style.cssText = "font-size:.75rem;color:var(--secondary-text-color)";
    hint.textContent = "Single use, ~10 minutes.";
    body.appendChild(hint);
  }

  getCardSize() {
    return 4;
  }
}
customElements.define("ada-pair-qr-card", AdaPairQrCard);
