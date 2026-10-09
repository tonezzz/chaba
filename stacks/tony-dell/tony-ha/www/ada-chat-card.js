// ada-chat-card — HA-native Ada text chat embedded in a Lovelace card.
// Same Gemini Live session as the voice card, text turns in, transcript out.
// Reuses the voice card's per-device key flow: script.ada_voice_key mints a
// ha-<device8> key server-side; the key and device_id live in the SAME
// localStorage slots (ada_voice_api_key / ada_voice_device_id) so one browser
// counts as one device across both cards. First WS connect TOFU-binds the
// key to device_id; a 4401 close re-mints once, then shows the unlock field.
// Server PCM audio frames are received but dropped (text-only surface).
//
// Config:
//   title:    card title (default "Ada chat")
//   instance: ada instance key, e.g. tony|michael (default tony)
//   ws_url:   wss://idc03.taila0626a.ts.net/apps/ha/ada-tony/ws   (default)
//   height:   log height (default 260px)
//   api_key:  <key>   optional — normally unset, card self-mints
//
// Attach: the 📎 button uploads a photo/document to
// POST {api_base}/api/documents/intake (client-downscaled to ~2400px first),
// then queues a "[document uploaded via card]" session note that is sent over
// the ws only while the session is idle — mid-turn text turns can abort the
// stream (same flow as ada-voice-card).

const ACC_KEY_STORAGE = "ada_voice_api_key";
const ACC_DEVICE_STORAGE = "ada_voice_device_id";
const ACC_DEFAULT_WS = "wss://idc03.taila0626a.ts.net/apps/ha/ada-tony/ws";

// Endpoint resolution order: explicit ws_url config > routes.json
// (generated from docs/ssot/infrastructure/ssot.routes.yml, served to HA
// cards as /local/routes.json) > literal fallback. Hostnames must not
// live in card code — the registry is the single source (edge-route-registry).
let _accRoutesP = null;
async function accResolveWs(cfg) {
  if (cfg && cfg.ws_url) return cfg.ws_url;
  try {
    if (!_accRoutesP)
      _accRoutesP = fetch("/local/routes.json")
        .then(r => (r.ok ? r.json() : null)).catch(() => null);
    const reg = await _accRoutesP;
    const ws = reg && reg.routes && reg.routes["ada-tony"] &&
      reg.routes["ada-tony"].ws;
    if (ws) return ws;
  } catch (e) { /* fall through to literal */ }
  return ACC_DEFAULT_WS;
}

class AdaChatCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._state = "idle";
    this._socket = null;
    this._connecting = false;
    this._mintRetried = false;
    this._assistantEntry = null;
    this._docNotes = [];      // queued "document uploaded" session notes
    this._docUploading = false;
    this._responseActive = false;

    this._card = document.createElement("ha-card");
    this._card.header = this._config.title || "Ada chat";
    const body = document.createElement("div");
    body.style.cssText = "padding:0 16px 16px;display:flex;flex-direction:column;gap:8px";

    // status row: live dot + status text + connect/disconnect buttons
    const row = document.createElement("div");
    row.style.cssText = "display:flex;align-items:center;gap:8px";
    this._dot = document.createElement("span");
    this._dot.className = "acc-status-dot";
    this._dot.style.cssText =
      "width:8px;height:8px;border-radius:50%;flex:none;" +
      "background:var(--disabled-text-color,#777);transition:background .3s";
    this._status = document.createElement("div");
    this._status.className = "acc-status";
    this._status.style.cssText = "flex:1;font-size:.8rem;color:var(--secondary-text-color)";
    this._status.textContent = "Disconnected";
    this._connectBtn = this._btn("Connect");
    this._connectBtn.className = "acc-connect";
    this._connectBtn.onclick = () => this._connect();
    this._disconnectBtn = this._btn("Disconnect");
    this._disconnectBtn.className = "acc-disconnect";
    this._disconnectBtn.disabled = true;
    this._disconnectBtn.onclick = () => this._teardown(true);
    // YOLO button — fullscreen live view of the xiaomi_c201 detection feed
    // (mn01 yolo-xiaomi service via Caddy /apps/yolo/api proxy).
    this._yoloBtn = this._btn("🧍 YOLO");
    this._yoloBtn.className = "acc-yolo";
    this._yoloBtn.title = "Live YOLO detection view (fullscreen)";
    this._yoloBtn.onclick = () => this._openYolo();
    row.append(this._dot, this._status, this._connectBtn, this._disconnectBtn, this._yoloBtn);
    body.appendChild(row);

    // transcript log — bubble layout; bubbles handle their own wrapping
    this._log = document.createElement("div");
    this._log.style.cssText =
      `height:${this._config.height || "260px"};overflow-y:auto;font-size:.85rem;line-height:1.45;` +
      "padding:10px 10px 6px;border-radius:10px;background:var(--secondary-background-color,#1c2128);" +
      "display:flex;flex-direction:column;gap:6px";
    body.appendChild(this._log);

    // typing indicator — shown while Ada is composing, hidden on first delta
    this._typing = document.createElement("div");
    this._typing.className = "acc-typing";
    this._typing.style.cssText =
      "align-self:flex-start;display:none;align-items:center;gap:5px;padding:6px 12px;" +
      "border-radius:14px 14px 14px 4px;background:var(--card-background-color,#2b3138);" +
      "color:var(--secondary-text-color);font-size:.78rem";
    this._typing.innerHTML =
      "Ada is typing <span class='acc-dots'><span>.</span><span>.</span><span>.</span></span>";
    const dots = this._typing.querySelectorAll(".acc-dots span");
    dots.forEach((d, i) => {
      d.style.cssText = "display:inline-block;animation:acc-blink 1.2s infinite;" +
        `animation-delay:${i * 0.2}s;opacity:.4`;
    });
    if (!document.getElementById("acc-typing-anim")) {
      const st = document.createElement("style");
      st.id = "acc-typing-anim";
      st.textContent =
        "@keyframes acc-blink{0%,60%,100%{opacity:.25;transform:translateY(0)}" +
        "30%{opacity:1;transform:translateY(-2px)}}";
      document.head.appendChild(st);
    }

    // input row
    const inRow = document.createElement("div");
    inRow.style.cssText = "display:flex;gap:6px";
    this._input = document.createElement("input");
    this._input.className = "acc-input";
    this._input.type = "text";
    this._input.placeholder = "Message Ada…";
    this._input.disabled = true;
    this._input.style.cssText =
      "flex:1;padding:6px 8px;border-radius:6px;border:1px solid var(--divider-color,#444);" +
      "background:var(--secondary-background-color,#1c2128);color:var(--primary-text-color);font-size:.85rem";
    this._input.addEventListener("keydown", (e) => { if (e.key === "Enter") this._send(); });
    this._sendBtn = this._btn("Send");
    this._sendBtn.className = "acc-send";
    this._sendBtn.disabled = true;
    this._sendBtn.style.background = "var(--primary-color,#03a9f4)";
    this._sendBtn.style.color = "var(--text-primary-color,#fff)";
    this._sendBtn.style.borderColor = "var(--primary-color,#03a9f4)";
    this._sendBtn.onclick = () => this._send();
    // Attach button — upload a photo/document for Ada to assess, then
    // archive/print via chat. capture-less accept still offers the camera
    // on iOS/Android pickers.
    this._attachBtn = this._btn("📎");
    this._attachBtn.className = "acc-attach";
    this._attachBtn.title = "Upload a document/photo for Ada";
    this._attachBtn.disabled = true;
    this._attachBtn.onclick = () => this._fileInput?.click();
    this._fileInput = document.createElement("input");
    this._fileInput.type = "file";
    this._fileInput.accept = "image/*";
    this._fileInput.style.display = "none";
    this._fileInput.onchange = () => {
      const f = this._fileInput.files && this._fileInput.files[0];
      this._fileInput.value = "";
      if (f) this._uploadDoc(f);
    };
    inRow.append(this._input, this._attachBtn, this._sendBtn);
    body.appendChild(inRow);
    body.appendChild(this._fileInput);  // must be in-DOM for Safari pickers

    // unlock row — shown when minting fails twice / no key available
    this._unlockRow = document.createElement("div");
    this._unlockRow.style.cssText = "display:none;gap:6px;align-items:center";
    this._unlockInput = document.createElement("input");
    this._unlockInput.type = "password";
    this._unlockInput.placeholder = "Ada device key (or ?api_key= link)";
    this._unlockInput.style.cssText = this._input.style.cssText;
    const save = this._btn("Save");
    const apply = () => {
      let v = (this._unlockInput.value || "").trim();
      if (!v) return;
      const m = v.match(/[?&]api_key=([^&#]+)/);
      if (m) v = decodeURIComponent(m[1]);
      localStorage.setItem(ACC_KEY_STORAGE, v);
      this._unlockInput.value = "";
      this._unlockRow.style.display = "none";
      this._setStatus("Key saved — tap Connect");
      this._render();
    };
    save.onclick = apply;
    this._unlockInput.addEventListener("keydown", (e) => { if (e.key === "Enter") apply(); });
    this._unlockRow.append(this._unlockInput, save);
    body.appendChild(this._unlockRow);

    this._card.appendChild(body);
    this.appendChild(this._card);
  }

  set hass(hass) { this._hass = hass; }

  // ---------- auth (same slots/flow as ada-voice-card) ----------

  _deviceId() {
    let id = localStorage.getItem(ACC_DEVICE_STORAGE);
    if (!id) {
      id = (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`).replace(/-/g, "");
      localStorage.setItem(ACC_DEVICE_STORAGE, id);
    }
    return id;
  }

  _apiKey() {
    if (this._config.api_key) return this._config.api_key;
    const params = new URLSearchParams(location.search);
    const fromUrl = params.get("api_key");
    if (fromUrl) localStorage.setItem(ACC_KEY_STORAGE, fromUrl);
    return localStorage.getItem(ACC_KEY_STORAGE) || "";
  }

  async _mintKey() {
    if (!this._hass) return null;
    try {
      const res = await this._hass.callWS({
        type: "call_service",
        domain: "script",
        service: "ada_voice_key",
        service_data: {
          instance: this._config.instance || "tony",
          device_id: this._deviceId(),
        },
        return_response: true,
      });
      const key = res?.response?.content?.api_key || null;
      if (key) localStorage.setItem(ACC_KEY_STORAGE, key);
      return key;
    } catch {
      return null;
    }
  }

  // ---------- log ----------

  _setStatus(t) {
    if (this._status) this._status.textContent = t;
    if (this._dot) {
      const colors = {
        connected: "var(--success-color,#4caf50)",
        connecting: "var(--warning-color,#ffc107)",
        locked: "var(--error-color,#f44336)",
        error: "var(--error-color,#f44336)",
      };
      this._dot.style.background =
        colors[this._state] || "var(--disabled-text-color,#777)";
    }
  }

  _nearBottom() {
    return this._log.scrollHeight - this._log.scrollTop - this._log.clientHeight < 60;
  }

  _scrollDown(force = false) {
    if (force || this._nearBottom()) this._log.scrollTop = this._log.scrollHeight;
  }

  _stamp() {
    const d = new Date();
    return d.toTimeString().slice(0, 5);
  }

  // Chat bubble: user right (accent-tinted), Ada left (surface), voice
  // user-side with a 🎤 tag. Returns the text container for streaming appends.
  _bubble(kind, text) {
    const mine = kind === "user" || kind === "voice";
    const d = document.createElement("div");
    // agent-inspectable-dom: stable hooks for playlive/Playwright assertions
    d.className = `acc-bubble acc-bubble-${kind}`;
    d.style.cssText =
      `align-self:${mine ? "flex-end" : "flex-start"};max-width:82%;` +
      `padding:6px 12px;border-radius:14px;white-space:pre-wrap;word-break:break-word;` +
      (mine
        ? "border-bottom-right-radius:4px;background:color-mix(in srgb,var(--primary-color,#03a9f4) 22%,transparent);" +
          "color:var(--primary-text-color)"
        : "border-bottom-left-radius:4px;background:var(--card-background-color,#2b3138);" +
          "color:var(--primary-text-color)");
    if (kind === "voice") {
      const tag = document.createElement("span");
      tag.style.cssText = "font-size:.72rem;opacity:.7;margin-right:5px";
      tag.textContent = "🎤";
      d.appendChild(tag);
    }
    const body = document.createElement("span");
    body.textContent = text;
    d.appendChild(body);
    const ts = document.createElement("span");
    ts.style.cssText = "display:block;font-size:.65rem;opacity:.45;margin-top:2px;text-align:right";
    ts.textContent = this._stamp();
    d.appendChild(ts);
    return { el: d, body };
  }

  _showTyping() {
    if (!this._typing) return;
    this._typing.style.display = "flex";
    this._log.appendChild(this._typing);
    this._scrollDown();
  }

  _hideTyping() {
    if (this._typing) this._typing.style.display = "none";
  }

  _add(who, text, color) {
    // who: 'You' (typed), 'Voice' (mic transcript), 'Ada' (assistant)
    const kind = who === "You" ? "user" : who === "Voice" ? "voice" : "ada";
    const { el, body } = this._bubble(kind, text);
    this._log.appendChild(el);
    this._scrollDown(true);  // own message / new turn always lands visible
    return { lastChild: body, el, body };
  }

  _system(text) {
    const d = document.createElement("div");
    d.className = "acc-system";
    d.style.cssText =
      "align-self:center;color:var(--secondary-text-color,#888);font-size:.75rem;text-align:center";
    d.textContent = `· ${text}`;
    this._log.appendChild(d);
    this._scrollDown();
  }

  _flushAssistant() {
    this._assistantEntry = null;
  }

  // ---------- document upload ----------

  _apiBase() {
    const ws = this._wsBase || this._config.ws_url || ACC_DEFAULT_WS;
    return ws.replace(/^ws(s?):/, "http$1:").replace(/\/ws\/?$/, "");
  }

  async _uploadDoc(file) {
    if (this._docUploading) return;
    this._docUploading = true;
    if (!this._wsBase) this._wsBase = await accResolveWs(this._config);
    this._setStatus(`Uploading ${file.name}…`);
    try {
      const blob = await this._downscale(file);
      const b64 = await new Promise((res, rej) => {
        const r = new FileReader();
        r.onload = () => res(String(r.result).split(",", 2)[1]);
        r.onerror = rej;
        r.readAsDataURL(blob);
      });
      const post = () => fetch(`${this._apiBase()}/api/documents/intake`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": this._apiKey(),
        },
        body: JSON.stringify({
          image_b64: b64, image_mime: blob.type || "image/jpeg",
          filename: file.name, mode: "both",
        }),
      });
      let resp = await post();
      // 401 = stored key is stale/revoked — re-mint once and retry
      // (ws layer already does this on a 4401 close; intake needs its own).
      if (resp.status === 401 && !this._config.api_key) {
        localStorage.removeItem(ACC_KEY_STORAGE);
        if (await this._mintKey()) resp = await post();
      }
      const out = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(out.detail || `HTTP ${resp.status}`);
      const w = (out.measured || {}).width || "?";
      const h = (out.measured || {}).height || "?";
      const warn = (out.warnings || []).length ? " ⚠ " + out.warnings.join("; ") : "";
      this._add("You", `📎 ${file.name}`, "var(--success-color,#4caf50)");
      this._system(`${file.name} → ${out.doc_type} ${w}×${h}${warn}`);
      this._setStatus(this._socket ? "Connected — type below" : "Disconnected");
      // Session note — sent when the session is idle so it never lands
      // mid-response (mid-turn text turns can abort the stream).
      const note =
        `[document uploaded via card] file=${file.name} intake_key=${out.key} ` +
        `type=${out.doc_type} size=${w}x${h}` +
        (warn ? ` warnings=${out.warnings.join("; ")}` : "") +
        " — ask what to do with it (archive/print); the intake key is held in RAM only.";
      this._docNotes.push(note);
      this._flushDocNotes();
    } catch (e) {
      this._system(`📎 upload failed: ${e.message || e}`);
      this._setStatus(this._socket ? "Connected — type below" : "Disconnected");
    } finally {
      this._docUploading = false;
      this._render();
    }
  }

  async _downscale(file, maxSide = 2400, quality = 0.87) {
    // Phone shots are 10-15MB; intake needs at most ~2400px for 300dpi A4.
    try {
      const bmp = await createImageBitmap(file);
      const scale = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
      if (scale >= 1) return file;
      const c = document.createElement("canvas");
      c.width = Math.round(bmp.width * scale);
      c.height = Math.round(bmp.height * scale);
      c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
      return await new Promise((res) =>
        c.toBlob((b) => res(b || file), "image/jpeg", quality));
    } catch {
      return file;  // e.g. HEIC the browser can't decode — let the server try
    }
  }

  _flushDocNotes() {
    // Never inject a text turn while Ada is mid-response — queue until the
    // response completes (or a reconnect flushes on 'ready').
    if (!this._docNotes.length) return;
    if (!this._socket || this._socket.readyState !== 1) return;
    if (this._responseActive) return;
    const notes = this._docNotes.splice(0);
    for (const text of notes) {
      try { this._socket.send(JSON.stringify({ type: "text", text })); }
      catch { this._docNotes.unshift(text); break; }
    }
  }

  // ---------- ws ----------

  _handleControl(ev) {
    switch (ev.type) {
      case "ready":
        this._state = "connected";
        this._responseActive = false;
        this._setStatus("Connected — type below");
        this._flushDocNotes();
        break;
      case "speech_started":
        this._setStatus("Voice input in progress…");
        break;
      case "speech_stopped":
        this._setStatus(this._socket ? "Connected — type below" : "Disconnected");
        this._flushDocNotes();
        break;
      case "user_transcript":
        this._add("Voice", ev.text, "var(--success-color,#4caf50)");
        break;
      case "assistant_transcript_delta": {
        this._hideTyping();
        if (!this._assistantEntry)
          this._assistantEntry = this._add("Ada", "", "var(--primary-color,#03a9f4)").lastChild;
        this._assistantEntry.textContent += ev.text;
        this._scrollDown();
        break;
      }
      case "response_started":
        this._responseActive = true;
        this._flushAssistant();
        this._showTyping();
        break;
      case "response_completed":
      case "clear_audio":
        this._responseActive = false;
        this._hideTyping();
        this._flushAssistant();
        this._flushDocNotes();
        break;
      case "response_interrupted":
        this._responseActive = false;
        this._hideTyping();
        this._flushAssistant();
        this._system("(interrupted)");
        this._flushDocNotes();
        break;
      case "live_reconnecting":
        this._setStatus("Reconnecting…");
        break;
      case "error":
        this._system(`Error: ${ev.message || ev.type}`);
        break;
    }
    this._render();
  }

  async _connect(isRetry = false) {
    if (this._connecting || this._socket) return;
    this._connecting = true;
    if (!isRetry) this._mintRetried = false;
    this._state = "connecting";
    this._setStatus("Pairing this device…");
    this._render();
    try {
      if (!this._apiKey() && !(await this._mintKey())) throw new Error("locked");
      this._setStatus("Connecting to Ada…");
      if (!this._wsBase) this._wsBase = await accResolveWs(this._config);
      const wsUrl = `${this._wsBase}`
        + `?device_id=${encodeURIComponent(this._deviceId())}`
        + `&api_key=${encodeURIComponent(this._apiKey())}`;
      let opened = false;
      this._socket = new WebSocket(wsUrl);
      this._socket.binaryType = "arraybuffer";
      this._socket.onopen = () => { opened = true; };
      this._socket.onmessage = (m) => {
        if (typeof m.data === "string") this._handleControl(JSON.parse(m.data));
        // binary PCM audio frames: dropped — this card is text-only
      };
      this._socket.onerror = () => this._system("WebSocket error");
      this._socket.onclose = async (e) => {
        // A handshake rejection (HTTP 403 — stale/foreign key) surfaces as
        // 1006, not 4401 — the server never accepted the socket. Treat both
        // as key rejection: drop the cached key, re-mint, retry once.
        const rejected = e.code === 4401 || (!opened && e.code !== 1000);
        if (rejected && !this._mintRetried) {
          this._mintRetried = true;
          localStorage.removeItem(ACC_KEY_STORAGE);
          await this._teardown(false);
          this._connect(true);
          return;
        }
        if (rejected) {
          localStorage.removeItem(ACC_KEY_STORAGE);
          this._state = "locked";
          this._setStatus("Key rejected — paste a key below");
        }
        this._teardown(false);
      };
    } catch (err) {
      if (err && err.message === "locked") {
        this._state = "locked";
        this._setStatus("Add a device key to unlock");
      } else {
        this._state = "error";
        this._setStatus(err.message || "Connection failed");
      }
      await this._teardown(false);
    } finally {
      this._connecting = false;
      this._render();
    }
  }

  async _teardown(closeSocket = true) {
    if (closeSocket && this._socket && this._socket.readyState < WebSocket.CLOSING)
      this._socket.close(1000, "user disconnect");
    this._socket = null;
    this._assistantEntry = null;
    this._responseActive = false;
    if (this._state !== "locked" && this._state !== "error") {
      this._state = "idle";
      this._setStatus("Disconnected");
    }
    this._render();
  }

  _send() {
    const text = (this._input.value || "").trim();
    if (!text || !this._socket || this._socket.readyState !== WebSocket.OPEN) return;
    this._socket.send(JSON.stringify({ type: "text", text }));
    this._add("You", text, "var(--success-color,#4caf50)");
    this._input.value = "";
    this._input.focus();
  }

  _render() {
    if (!this._connectBtn) return;
    const connected = this._state === "connected" || !!this._socket;
    this._connectBtn.disabled = connected || this._connecting || this._state === "locked";
    this._disconnectBtn.disabled = !connected;
    this._input.disabled = !connected;
    this._sendBtn.disabled = !connected;
    if (this._attachBtn) this._attachBtn.disabled = !connected || this._docUploading;
    this._unlockRow.style.display = this._state === "locked" ? "flex" : "none";
  }

  _yoloBase() {
    return (this._config.yolo_base ||
      "https://tony-dell.taila0626a.ts.net/apps/yolo/api").replace(/\/$/, "");
  }

  _openYolo() {
    if (this._yoloOverlay) return;
    const base = this._yoloBase();
    const ov = document.createElement("div");
    ov.className = "acc-yolo-overlay";
    ov.style.cssText =
      "position:fixed;inset:0;z-index:9999;background:rgba(8,10,14,.97);" +
      "display:flex;flex-direction:column;color:#eee";

    // header: title + live counts + close
    const head = document.createElement("div");
    head.style.cssText =
      "display:flex;align-items:center;gap:12px;padding:10px 16px;" +
      "border-bottom:1px solid #2a2f36;flex:none";
    const ttl = document.createElement("div");
    ttl.style.cssText = "font-size:1rem;font-weight:600";
    ttl.textContent = "🧍 YOLO — live detection";
    const stats = document.createElement("div");
    stats.style.cssText = "flex:1;font-size:.8rem;color:#9aa4b0";
    stats.textContent = "connecting…";
    const close = document.createElement("button");
    close.textContent = "✕ close — Esc";
    close.style.cssText =
      "padding:4px 12px;border-radius:6px;border:1px solid #3a414a;" +
      "background:#1c2128;color:#eee;cursor:pointer;font-size:.8rem";
    close.onclick = () => this._closeYolo();
    head.append(ttl, stats, close);
    ov.appendChild(head);

    // live annotated frame
    const imgWrap = document.createElement("div");
    imgWrap.style.cssText = "flex:1;display:flex;align-items:center;justify-content:center;min-height:0;padding:8px";
    const img = document.createElement("img");
    img.style.cssText = "max-width:100%;max-height:100%;object-fit:contain;border-radius:8px";
    img.alt = "YOLO annotated frame";
    imgWrap.appendChild(img);
    ov.appendChild(imgWrap);

    const foot = document.createElement("div");
    foot.style.cssText =
      "flex:none;padding:8px 16px;border-top:1px solid #2a2f36;" +
      "font-size:.75rem;color:#8b94a0;display:flex;gap:16px";
    foot.textContent = "xiaomi_c201 via mn01:8780 · refresh ~2s";
    ov.appendChild(foot);

    const onKey = (e) => { if (e.key === "Escape") this._closeYolo(); };
    document.addEventListener("keydown", onKey);

    const tick = async () => {
      img.src = `${base}/image?v=${Date.now()}`;
      try {
        const r = await fetch(`${base}/detect`, { cache: "no-store" });
        const d = await r.json();
        if (d.error) {
          stats.textContent = `feed error — ${String(d.error).slice(0, 90)}`;
          return;
        }
        const counts = Object.entries(d.counts || {})
          .map(([k, v]) => `${k}:${v}`).join("  ");
        stats.textContent =
          `persons: ${d.person_count ?? 0}   ${counts}` +
          `   · ${d.ts || ""}`.slice(0, 140);
      } catch (e) {
        stats.textContent = "yolo service unreachable";
      }
    };
    this._yoloTimer = setInterval(tick, 2000);
    tick();
    this._yoloOverlay = ov;
    this._yoloKeyHandler = onKey;
    document.body.appendChild(ov);
  }

  _closeYolo() {
    if (this._yoloTimer) { clearInterval(this._yoloTimer); this._yoloTimer = null; }
    if (this._yoloKeyHandler) {
      document.removeEventListener("keydown", this._yoloKeyHandler);
      this._yoloKeyHandler = null;
    }
    if (this._yoloOverlay) { this._yoloOverlay.remove(); this._yoloOverlay = null; }
  }

  _btn(label) {
    const b = document.createElement("button");
    b.textContent = label;
    b.style.cssText =
      "padding:2px 10px;border-radius:6px;border:1px solid var(--divider-color,#444);" +
      "background:var(--secondary-background-color,#1c2128);color:var(--primary-text-color);cursor:pointer;font-size:.75rem;white-space:nowrap";
    return b;
  }

  connectedCallback() {
    // Auto-connect on view load (default) — chat shouldn't need a Connect
    // click first. autoconnect: false in config restores the manual flow.
    if (this._config && this._config.autoconnect !== false
        && !this._socket && !this._connecting) this._connect();
  }

  disconnectedCallback() {
    this._closeYolo();
    if (this._socket) this._teardown(true);
  }

  getCardSize() { return 6; }
}
customElements.define("ada-chat-card", AdaChatCard);
