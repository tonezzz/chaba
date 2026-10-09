// chaba-profile-panel.js — injects a "Chaba" card at the top of the
// /profile page. One button mints a device key via script.chaba_pwa_invite
// (server-side admin key never reaches the browser) and pops a QR so an
// iPhone can scan → open the redeem link → save as PWA. Explanation is
// rendered in the user's HA language (en/th).
// Loaded via frontend.extra_module_url.
(function () {
  const TAG = "chaba-profile-panel";
  const DBG = "chaba-panel:";

  const STR = {
    en: {
      title: "Chaba",
      btn: "Get my QR — install Ada on this iPhone",
      busy: "Minting key…",
      how: "Point your iPhone camera at the QR → open the link → Share → Add to Home Screen. The app appears as ADA-TONY with your name and signs you in automatically.",
      hint: "Single use, ~10 minutes. Scan from the phone you want to pair.",
      fail: "Key minting failed — check Ada backend.",
    },
    th: {
      title: "Chaba",
      btn: "ขอ QR — ติดตั้ง Ada บน iPhone เครื่องนี้",
      busy: "กำลังสร้างคีย์…",
      how: "เปิดกล้อง iPhone สแกน QR → แตะลิงก์ → Share → Add to Home Screen. แอปจะขึ้นชื่อ ADA-TONY พร้อมชื่อของคุณ และล็อกอินอัตโนมัติ",
      hint: "ใช้ได้ครั้งเดียว หมดอายุ ~10 นาที — สแกนจากเครื่องที่จะผูก",
      fail: "สร้างคีย์ไม่สำเร็จ — เช็ค Ada backend",
    },
  };

  function hassObj() {
    const el = document.querySelector("home-assistant");
    return el && el.hass;
  }
  function myLang() {
    const h = hassObj();
    const lang = (h && h.locale && h.locale.language) ||
                 (h && h.selectedLanguage) || "en";
    return lang.startsWith("th") ? "th" : "en";
  }

  class ChabaProfilePanel extends HTMLElement {
    constructor() { super(); this._busy = false; }
    connectedCallback() {
      if (this._built) return;
      this._built = true;
      const sr = this.attachShadow({ mode: "open" });
      sr.innerHTML = `
        <style>
          .card { background: var(--card-background-color,#fff);
                  color: var(--primary-text-color,#212121);
                  border-radius: var(--ha-card-border-radius,12px);
                  box-shadow: var(--ha-card-box-shadow,0 2px 8px rgba(0,0,0,.15));
                  padding: 16px; margin: 0 0 16px; }
          .t { font-size: 1.1rem; font-weight: 600; margin-bottom: 8px }
          .how { font-size: .9rem; color: var(--secondary-text-color,#727272);
                 margin: 0 0 12px }
          button { font: inherit; font-size: 1rem; padding: 12px 18px;
                   border-radius: 8px; border: none; cursor: pointer;
                   background: var(--primary-color,#03a9f4); color: #fff;
                   min-height: 48px; }
          .qr { margin-top: 14px; display:none; text-align:center }
          .qr .box { background:#fff; display:inline-block; padding:10px;
                     border-radius:8px }
          .qr .url { font-size:.75rem; word-break:break-all;
                     color:var(--secondary-text-color,#727272);
                     margin-top:8px; user-select:text }
          .hint { font-size:.75rem; color:var(--secondary-text-color,#727272);
                  margin-top:6px }
          .err { color: var(--error-color,#db4437); font-size:.9rem;
                 margin-top:8px }
        </style>
        <div class="card">
          <div class="t"></div>
          <p class="how"></p>
          <button></button>
          <div class="qr"><div class="box"></div><div class="url"></div>
               <div class="hint"></div></div>
          <div class="err" style="display:none"></div>
        </div>`;
      const s = STR[myLang()];
      const r = this.shadowRoot;
      r.querySelector(".t").textContent = s.title;
      r.querySelector(".how").textContent = s.how;
      r.querySelector(".hint").textContent = s.hint;
      const b = r.querySelector("button");
      b.textContent = s.btn;
      b.onclick = () => this._mint();
      const pump = () => {           // hass may not exist at inject time
        const h = hassObj();
        if (h) this._hass = h;
        else if (this.isConnected) setTimeout(pump, 500);
      };
      pump();
    }

    async _mint() {
      if (this._busy) return;
      const h = this._hass || hassObj();
      if (!h) return;
      this._busy = true;
      const r = this.shadowRoot, s = STR[myLang()];
      const btn = r.querySelector("button");
      const err = r.querySelector(".err");
      btn.textContent = s.busy; err.style.display = "none";
      try {
        const name = (h.user && h.user.name) || "device";
        const call = (svc) => h.connection.sendMessagePromise({
          type: "call_service", domain: "script",
          service: svc, return_response: true,
          service_data: { name: `pwa-${name}`, instance: "tony" },
        });
        // script returns the rest_command response var:
        // {status, headers, content: {qr_svg, redeem_url, ...}}
        let resp = await call("chaba_pwa_invite");
        let body = ((resp && resp.response) || {}).service_response ||
                   ((resp && resp.response) || {});
        if (body.status === 409) {           // key exists -> re-pair it
          resp = await call("chaba_pwa_repair");
          body = ((resp && resp.response) || {}).service_response ||
                 ((resp && resp.response) || {});
        }
        const content = body.content || body;
        const svg = content.qr_svg, url = content.redeem_url;
        if (!url) throw new Error("no redeem_url — got " +
          JSON.stringify(body).slice(0, 120));
        const qr = r.querySelector(".qr");
        qr.style.display = "block";
        if (svg) r.querySelector(".box").innerHTML = svg;
        r.querySelector(".url").textContent = url;
        btn.textContent = s.btn;
      } catch (e) {
        err.textContent = s.fail + " (" + (e.message || e) + ")";
        err.style.display = "block";
        btn.textContent = s.btn;
      }
      this._busy = false;
    }
  }
  try { customElements.define(TAG, ChabaProfilePanel); }
  catch (e) { console.log(DBG, "define failed", e); }

  // --- deep search: walk light DOM + every shadowRoot for the profile panel
  function* walk(root) {
    for (const el of root.querySelectorAll("*")) {
      yield el;
      if (el.shadowRoot) yield* walk(el.shadowRoot);
    }
  }
  function findProfileHost() {
    if (!location.pathname.startsWith("/profile")) return null;
    for (const el of walk(document.body)) {
      if (!/profile/i.test(el.tagName) || !el.shadowRoot) continue;
      const host = el.shadowRoot.querySelector(".container") ||
                   el.shadowRoot.querySelector(".content") ||
                   [...el.shadowRoot.children].find(
                     (c) => c.tagName !== "STYLE") || el;
      console.log(DBG, "host found:", el.tagName, "->", host.tagName);
      return host;
    }
    return null;
  }

  let card;
  function tryInject() {
    const host = findProfileHost();
    if (!host) return;
    if (!card || !card.isConnected) {
      card = document.createElement(TAG);
      host.insertBefore(card, host.firstChild);
      console.log(DBG, "injected into", host.tagName);
    }
  }

  // Floating fallback — proves the module loaded even if DOM injection
  // misses (visible bottom-right chip on /profile only).
  let chip;
  function tick() {
    if (!location.pathname.startsWith("/profile")) {
      if (chip) { chip.remove(); chip = null; }
      return;
    }
    const injected = card && card.isConnected;
    if (injected) { if (chip) { chip.remove(); chip = null; } return; }
    if (!chip) {
      chip = document.createElement("div");
      chip.textContent = "Chaba";
      chip.style.cssText =
        "position:fixed;right:14px;bottom:14px;z-index:9999;padding:10px 16px;" +
        "border-radius:20px;background:#03a9f4;color:#fff;font:600 .9rem sans-serif;" +
        "cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.4)";
      chip.title = "Chaba module loaded — profile host not found yet";
      chip.onclick = () => { tryInject(); };
      document.body.appendChild(chip);
      console.log(DBG, "fallback chip shown (host not found)");
    }
  }

  window.addEventListener("location-changed", tryInject);
  new MutationObserver(tryInject).observe(document.body,
    { childList: true, subtree: true });
  setInterval(() => { tryInject(); tick(); }, 2000);
  console.log(DBG, "module loaded");
})();
