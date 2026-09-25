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
//   ws_url:   wss://idc01.taila0626a.ts.net/apps/ha/ada-tony/ws   (default)
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
const ACC_DEFAULT_WS = "wss://idc01.taila0626a.ts.net/apps/ha/ada-tony/ws";

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

    // status row: status text + connect/disconnect buttons
    const row = document.createElement("div");
    row.style.cssText = "display:flex;align-items:center;gap:8px";
    this._status = document.createElement("div");
    this._status.style.cssText = "flex:1;font-size:.85rem;color:var(--secondary-text-color)";
    this._status.textContent = "Disconnected";
    this._connectBtn = this._btn("Connect");
    this._connectBtn.onclick = () => this._connect();
    this._disconnectBtn = this._btn("Disconnect");
    this._disconnectBtn.disabled = true;
    this._disconnectBtn.onclick = () => this._teardown(true);
    row.append(this._status, this._connectBtn, this._disconnectBtn);
    body.appendChild(row);

    // transcript log
    this._log = document.createElement("div");
    this._log.style.cssText =
      `height:${this._config.height || "260px"};overflow-y:auto;font-size:.82rem;line-height:1.5;` +
      "padding:6px 8px;border-radius:8px;background:var(--secondary-background-color,#1c2128);" +
      "white-space:pre-wrap;word-break:break-word";
    body.appendChild(this._log);

    // input row
    const inRow = document.createElement("div");
    inRow.style.cssText = "display:flex;gap:6px";
    this._input = document.createElement("input");
    this._input.type = "text";
    this._input.placeholder = "Message Ada…";
    this._input.disabled = true;
    this._input.style.cssText =
      "flex:1;padding:6px 8px;border-radius:6px;border:1px solid var(--divider-color,#444);" +
      "background:var(--secondary-background-color,#1c2128);color:var(--primary-text-color);font-size:.85rem";
    this._input.addEventListener("keydown", (e) => { if (e.key === "Enter") this._send(); });
    this._sendBtn = this._btn("Send");
    this._sendBtn.disabled = true;
    this._sendBtn.onclick = () => this._send();
    // Attach button — upload a photo/document for Ada to assess, then
    // archive/print via chat. capture-less accept still offers the camera
    // on iOS/Android pickers.
    this._attachBtn = this._btn("📎");
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

  _setStatus(t) { if (this._status) this._status.textContent = t; }

  _row(who, text, color) {
    const d = document.createElement("div");
    const tag = document.createElement("span");
    tag.style.cssText = `font-weight:600;color:${color};margin-right:6px`;
    tag.textContent = who;
    const body = document.createElement("span");
    body.textContent = text;
    d.append(tag, body);
    return d;
  }

  _add(who, text, color) {
    const el = this._row(who, text, color);
    this._log.appendChild(el);
    this._log.scrollTop = this._log.scrollHeight;
    return el;
  }

  _system(text) {
    const d = document.createElement("div");
    d.style.color = "var(--secondary-text-color,#888)";
    d.textContent = `· ${text}`;
    this._log.appendChild(d);
    this._log.scrollTop = this._log.scrollHeight;
  }

  _flushAssistant() {
    this._assistantEntry = null;
  }

  // ---------- document upload ----------

  _apiBase() {
    const ws = this._config.ws_url || ACC_DEFAULT_WS;
    return ws.replace(/^ws(s?):/, "http$1:").replace(/\/ws\/?$/, "");
  }

  async _uploadDoc(file) {
    if (this._docUploading) return;
    this._docUploading = true;
    this._setStatus(`Uploading ${file.name}…`);
    try {
      const blob = await this._downscale(file);
      const b64 = await new Promise((res, rej) => {
        const r = new FileReader();
        r.onload = () => res(String(r.result).split(",", 2)[1]);
        r.onerror = rej;
        r.readAsDataURL(blob);
      });
      const resp = await fetch(`${this._apiBase()}/api/documents/intake`, {
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
        if (!this._assistantEntry)
          this._assistantEntry = this._add("Ada", "", "var(--primary-color,#03a9f4)").lastChild;
        this._assistantEntry.textContent += ev.text;
        this._log.scrollTop = this._log.scrollHeight;
        break;
      }
      case "response_started":
        this._responseActive = true;
        this._flushAssistant();
        break;
      case "response_completed":
      case "clear_audio":
        this._responseActive = false;
        this._flushAssistant();
        this._flushDocNotes();
        break;
      case "response_interrupted":
        this._responseActive = false;
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
      const wsUrl = `${this._config.ws_url || ACC_DEFAULT_WS}`
        + `?device_id=${encodeURIComponent(this._deviceId())}`
        + `&api_key=${encodeURIComponent(this._apiKey())}`;
      this._socket = new WebSocket(wsUrl);
      this._socket.binaryType = "arraybuffer";
      this._socket.onmessage = (m) => {
        if (typeof m.data === "string") this._handleControl(JSON.parse(m.data));
        // binary PCM audio frames: dropped — this card is text-only
      };
      this._socket.onerror = () => this._system("WebSocket error");
      this._socket.onclose = async (e) => {
        if (e.code === 4401 && !this._mintRetried) {
          // Key revoked or bound to another device — re-mint and retry once.
          this._mintRetried = true;
          localStorage.removeItem(ACC_KEY_STORAGE);
          await this._teardown(false);
          this._connect(true);
          return;
        }
        if (e.code === 4401) {
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

  _btn(label) {
    const b = document.createElement("button");
    b.textContent = label;
    b.style.cssText =
      "padding:2px 10px;border-radius:6px;border:1px solid var(--divider-color,#444);" +
      "background:var(--secondary-background-color,#1c2128);color:var(--primary-text-color);cursor:pointer;font-size:.75rem;white-space:nowrap";
    return b;
  }

  disconnectedCallback() {
    if (this._socket) this._teardown(true);
  }

  getCardSize() { return 6; }
}
customElements.define("ada-chat-card", AdaChatCard);
