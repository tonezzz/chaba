// ada-voice-card — embedded Ada Gemini Live voice client for Lovelace.
// Ports the PWA transport (pwa/app.js) into a card: mic capture ->
// 16 kHz PCM16 over WebSocket, 24 kHz PCM16 playback via AudioWorklet.
// No iframe, no redirect — same backend session as the PWA.
//
// Config:
//   type: custom:ada-voice-card
//   ws_url:   wss://idc01.taila0626a.ts.net/apps/ha/ada-tony/ws   (default)
//   instance: tony | michael   (default tony — selects the backend + key name)
//   api_key:  <key>   optional — normally unset: the card auto-mints a
//             per-device issued key via script.ada_voice_key (server-side
//             redeem; the admin key never reaches the browser). The paste
//             field below is only a fallback when the script fails.
//   title:    Ada     optional
//
// Controls: the Mute button hard-mutes the mic (track disabled — nothing
// is captured or sent; press again to unmute). The "Auto" checkbox gates
// the mic on the card's local VAD: after local_speech_stopped the mic is
// auto-muted (audio still captured for VAD but not sent), and speaking
// again auto-resumes. Auto state persists in localStorage.

const AVC_INPUT_RATE = 16000;
const AVC_OUTPUT_RATE = 24000;
const AVC_DEFAULT_WS = "wss://idc01.taila0626a.ts.net/apps/ha/ada-tony/ws";
const AVC_KEY_STORAGE = "ada_voice_api_key";
const AVC_DEVICE_STORAGE = "ada_voice_device_id";
const AVC_AUTO_STORAGE = "ada_voice_auto_mute";

// Shared live-activity channel. The voice card publishes status/transcript
// events here; ada-activity-card elements on the same page render them
// log-style. Lives on window so it survives card reconnects/view switches.
const AVC_ACTIVITY = "__adaVoiceActivity";
function avcChannel() {
  return (window[AVC_ACTIVITY] = window[AVC_ACTIVITY] || { entries: [], subs: new Set() });
}
function avcLog(kind, text) {
  if (!text) return;
  const ch = avcChannel();
  const last = ch.entries[ch.entries.length - 1];
  if (last && last.kind === kind && last.text === text) return; // dedupe repeats
  const entry = { t: Date.now(), kind, text };
  ch.entries.push(entry);
  if (ch.entries.length > 300) ch.entries.splice(0, ch.entries.length - 300);
  ch.subs.forEach((fn) => { try { fn(entry); } catch {} });
}

class AdaVoiceCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._socket = null;
    this._stream = null;
    this._captureContext = null;
    this._playbackContext = null;
    this._captureNode = null;
    this._playbackNode = null;
    this._playbackAnalyser = null;
    this._playbackMeterFrame = null;
    this._connecting = false;
    this._assistantEntry = null;
    this._pendingAdaLog = null;
    this._assistantPlaying = false;
    this._localSpeech = false;
    this._speechAbove = 0;
    this._speechBelow = 0;
    this._noiseFloor = 0.004;
    this._micMuted = false;
    this._auto = localStorage.getItem(AVC_AUTO_STORAGE) === "1";
    this._autoMuted = false;
    this._mintRetried = false;
    this._state = "idle"; // idle | locked | connecting | listening | speaking | reconnecting | error
    this._build();
  }

  set hass(hass) { this._hass = hass; }

  _build() {
    this._card = document.createElement("ha-card");
    this._card.header = this._config.title || "Ada";
    const body = document.createElement("div");
    body.style.cssText = "padding:0 16px 16px;display:flex;flex-direction:column;gap:10px";

    const row = document.createElement("div");
    row.style.cssText = "display:flex;align-items:center;gap:12px";

    this._micBtn = document.createElement("button");
    this._micBtn.style.cssText =
      "width:56px;height:56px;border-radius:50%;border:2px solid var(--divider-color,#444);" +
      "background:var(--secondary-background-color,#1c2128);color:var(--primary-text-color);" +
      "cursor:pointer;font-size:24px;display:flex;align-items:center;justify-content:center;flex:none";
    this._micBtn.title = "Tap to talk to Ada";
    this._micBtn.onclick = () => this._toggle();
    this._micIcon = document.createElement("ha-icon");
    this._micIcon.setAttribute("icon", "mdi:microphone");
    this._micBtn.appendChild(this._micIcon);

    const mid = document.createElement("div");
    mid.style.cssText = "flex:1;display:flex;flex-direction:column;gap:4px;min-width:0";
    this._status = document.createElement("div");
    this._status.style.cssText = "font-size:.9rem";
    this._status.textContent = "Tap the mic to talk";
    this._level = document.createElement("div");
    this._level.style.cssText =
      "height:4px;border-radius:2px;background:var(--divider-color,#333);overflow:hidden;transition:opacity .2s";
    this._levelBar = document.createElement("div");
    this._levelBar.style.cssText =
      "height:100%;width:0%;background:var(--primary-color,#03a9f4);transition:width .05s linear";
    this._level.appendChild(this._levelBar);
    mid.append(this._status, this._level);

    this._muteBtn = document.createElement("button");
    this._muteBtn.style.cssText =
      "padding:4px 10px;border-radius:6px;border:1px solid var(--divider-color,#444);" +
      "background:var(--secondary-background-color,#1c2128);color:var(--primary-text-color);cursor:pointer;font-size:.75rem;white-space:nowrap";
    this._muteBtn.onclick = () => this._toggleMute();

    this._autoChk = document.createElement("input");
    this._autoChk.type = "checkbox";
    this._autoChk.checked = this._auto;
    this._autoChk.onchange = () => {
      this._auto = this._autoChk.checked;
      localStorage.setItem(AVC_AUTO_STORAGE, this._auto ? "1" : "0");
      if (!this._auto && this._autoMuted) {
        this._autoMuted = false;
        this._setStatus("Listening");
        this._render();
      }
    };
    const autoLabel = document.createElement("label");
    autoLabel.style.cssText =
      "display:flex;align-items:center;gap:4px;font-size:.75rem;cursor:pointer;white-space:nowrap;" +
      "color:var(--secondary-text-color)";
    autoLabel.title = "Auto-mute the mic when you stop speaking — speak again to resume";
    autoLabel.append(this._autoChk, document.createTextNode("Auto"));

    const ctl = document.createElement("div");
    ctl.style.cssText = "display:flex;flex-direction:column;gap:6px;align-items:stretch;flex:none";
    ctl.append(this._muteBtn, autoLabel);

    row.append(this._micBtn, mid, ctl);
    body.appendChild(row);

    this._line = document.createElement("div");
    this._line.style.cssText =
      "font-size:.85rem;color:var(--secondary-text-color);min-height:1.1em;overflow:hidden;" +
      "text-overflow:ellipsis;white-space:nowrap";
    body.appendChild(this._line);

    // Unlock row — shown when no usable key is configured/stored.
    this._unlockRow = document.createElement("div");
    this._unlockRow.style.cssText = "display:none;gap:6px;align-items:center";
    this._unlockInput = document.createElement("input");
    this._unlockInput.type = "password";
    this._unlockInput.placeholder = "Ada device key (or ?api_key= link)";
    this._unlockInput.style.cssText =
      "flex:1;padding:6px 8px;border-radius:6px;border:1px solid var(--divider-color,#444);" +
      "background:var(--secondary-background-color,#1c2128);color:var(--primary-text-color);font-size:.85rem";
    const save = document.createElement("button");
    save.textContent = "Save";
    save.style.cssText =
      "padding:6px 12px;border-radius:6px;border:1px solid var(--divider-color,#444);" +
      "background:var(--primary-color,#03a9f4);color:#fff;cursor:pointer;font-size:.8rem";
    const apply = () => {
      let v = (this._unlockInput.value || "").trim();
      if (!v) return;
      const m = v.match(/[?&]api_key=([^&#]+)/);       // accept a full unlock link too
      if (m) v = decodeURIComponent(m[1]);
      localStorage.setItem(AVC_KEY_STORAGE, v);
      this._unlockInput.value = "";
      this._unlockRow.style.display = "none";
      this._setStatus("Key saved — tap the mic");
      this._render();
    };
    save.onclick = apply;
    this._unlockInput.addEventListener("keydown", (e) => { if (e.key === "Enter") apply(); });
    this._unlockRow.append(this._unlockInput, save);
    body.appendChild(this._unlockRow);

    this._card.appendChild(body);
    this.appendChild(this._card);
    this._render();
  }

  // ---------- auth ----------

  _deviceId() {
    let id = localStorage.getItem(AVC_DEVICE_STORAGE);
    if (!id) {
      id = (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`).replace(/-/g, "");
      localStorage.setItem(AVC_DEVICE_STORAGE, id);
    }
    return id;
  }

  _apiKey() {
    if (this._config.api_key) return this._config.api_key;
    const params = new URLSearchParams(location.search);
    const fromUrl = params.get("api_key");
    if (fromUrl) localStorage.setItem(AVC_KEY_STORAGE, fromUrl);
    return localStorage.getItem(AVC_KEY_STORAGE) || "";
  }

  // Mint a per-device issued key through HA: script.ada_voice_key creates
  // (or re-pairs) ha-<device8> on the backend and redeems it server-side,
  // returning the raw key. The admin credential never leaves HA.
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
      if (key) localStorage.setItem(AVC_KEY_STORAGE, key);
      return key;
    } catch {
      return null;
    }
  }

  // ---------- audio ----------

  _downsample(input, inputRate, outputRate) {
    const ratio = inputRate / outputRate;
    const length = Math.floor(input.length / ratio);
    const output = new Int16Array(length);
    for (let i = 0; i < length; i++) {
      const start = Math.floor(i * ratio);
      const end = Math.max(start + 1, Math.floor((i + 1) * ratio));
      let sum = 0;
      for (let j = start; j < end && j < input.length; j++) sum += input[j];
      const sample = Math.max(-1, Math.min(1, sum / (end - start)));
      output[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
    }
    return output.buffer;
  }

  async _createPlayback() {
    this._playbackContext = new AudioContext({ sampleRate: AVC_OUTPUT_RATE, latencyHint: "interactive" });
    const workletSource = `
      class PCMPlayer extends AudioWorkletProcessor {
        constructor() {
          super();
          this.queue = [];
          this.offset = 0.0;
          this.step = 24000 / sampleRate;
          this.bufferedSamples = 0;
          this.playing = false;
          this.forceStart = false;
          this.startThreshold = 0;
          this.port.onmessage = e => {
            if (e.data.type === 'clear') {
              this.queue = []; this.offset = 0; this.bufferedSamples = 0;
              this.playing = false; this.forceStart = false;
            } else if (e.data.type === 'flush') {
              this.forceStart = true;
            } else {
              const chunk = new Int16Array(e.data);
              this.queue.push(chunk); this.bufferedSamples += chunk.length;
            }
          };
        }
        process(inputs, outputs) {
          const out = outputs[0][0]; out.fill(0); let n = 0;
          if (!this.playing) {
            if (this.bufferedSamples < this.startThreshold && !(this.forceStart && this.bufferedSamples)) return true;
            this.playing = true;
          }
          while (n < out.length && this.queue.length) {
            const chunk = this.queue[0];
            while (n < out.length && this.offset < chunk.length - 1) {
              const i = Math.floor(this.offset);
              const frac = this.offset - i;
              const s0 = chunk[i] / 32768;
              const s1 = chunk[i + 1] / 32768;
              out[n++] = s0 + (s1 - s0) * frac;
              this.bufferedSamples -= this.step;
              this.offset += this.step;
            }
            if (this.offset >= chunk.length - 1) {
              this.queue.shift();
              this.offset = Math.max(0, this.offset - (chunk.length - 1));
            }
          }
          if (!this.queue.length) { this.playing = false; this.forceStart = false; }
          return true;
        }
      }
      registerProcessor('pcm-player', PCMPlayer);`;
    const url = URL.createObjectURL(new Blob([workletSource], { type: "text/javascript" }));
    await this._playbackContext.audioWorklet.addModule(url);
    URL.revokeObjectURL(url);
    this._playbackNode = new AudioWorkletNode(this._playbackContext, "pcm-player", { outputChannelCount: [1] });
    this._playbackAnalyser = this._playbackContext.createAnalyser();
    this._playbackAnalyser.fftSize = 256;
    this._playbackAnalyser.smoothingTimeConstant = 0.68;
    this._playbackNode.connect(this._playbackAnalyser);
    this._playbackAnalyser.connect(this._playbackContext.destination);
    await this._playbackContext.resume();
    this._startPlaybackMeter();
  }

  _startPlaybackMeter() {
    const samples = new Float32Array(this._playbackAnalyser.fftSize);
    let smoothed = 0, last = 0;
    const measure = (now) => {
      if (!this._playbackAnalyser) return;
      this._playbackAnalyser.getFloatTimeDomainData(samples);
      let power = 0;
      for (const s of samples) power += s * s;
      const level = Math.min(1, Math.max(0, (Math.sqrt(power / samples.length) - 0.006) * 8.5));
      smoothed = level > smoothed ? smoothed * 0.48 + level * 0.52 : smoothed * 0.76 + level * 0.24;
      if (now - last >= 33) { this._setLevel(smoothed); last = now; }
      this._playbackMeterFrame = requestAnimationFrame(measure);
    };
    this._playbackMeterFrame = requestAnimationFrame(measure);
  }

  async _startMicrophone() {
    this._stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: false },
    });
    const track = this._stream.getAudioTracks()[0];
    track.enabled = !this._micMuted;
    this._captureContext = new AudioContext({ latencyHint: "interactive" });
    const source = this._captureContext.createMediaStreamSource(this._stream);
    this._captureNode = this._captureContext.createScriptProcessor(2048, 1, 1);
    const silent = this._captureContext.createGain();
    silent.gain.value = 0;
    this._captureNode.onaudioprocess = (event) => {
      const ws = this._socket;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      if (this._micMuted) return;
      const samples = event.inputBuffer.getChannelData(0);
      let power = 0;
      for (const s of samples) power += s * s;
      const rms = Math.sqrt(power / samples.length);
      if (!this._localSpeech) this._noiseFloor = this._noiseFloor * 0.98 + rms * 0.02;
      const startTh = Math.max(0.012, this._noiseFloor * 2.8);
      const stopTh = Math.max(0.008, this._noiseFloor * 1.7);
      if (!this._localSpeech) {
        this._speechAbove = rms > startTh ? this._speechAbove + 1 : 0;
        if (this._speechAbove >= 3) {
          this._localSpeech = true; this._speechBelow = 0;
          if (this._autoMuted) { this._autoMuted = false; this._setStatus("Listening"); this._render(); }
          ws.send(JSON.stringify({ type: "local_speech_started", rms, threshold: startTh }));
        }
      } else {
        this._speechBelow = rms < stopTh ? this._speechBelow + 1 : 0;
        if (this._speechBelow >= 12) {
          this._localSpeech = false; this._speechAbove = 0;
          ws.send(JSON.stringify({ type: "local_speech_stopped", rms, threshold: stopTh }));
          if (this._auto) { this._autoMuted = true; this._setStatus("Auto-muted — speak to resume"); this._render(); }
        }
      }
      if (!this._autoMuted)
        ws.send(this._downsample(samples, this._captureContext.sampleRate, AVC_INPUT_RATE));
    };
    source.connect(this._captureNode);
    this._captureNode.connect(silent);
    silent.connect(this._captureContext.destination);
    await this._captureContext.resume();
  }

  // ---------- websocket ----------

  _handleControl(ev) {
    switch (ev.type) {
      case "ready":
        this._state = "listening";
        this._setStatus("Connected — listening");
        break;
      case "speech_started":
        this._setStatus("Speech detected");
        break;
      case "speech_stopped":
        this._setStatus("Listening");
        break;
      case "clear_audio":
        this._assistantPlaying = false;
        this._playbackNode?.port.postMessage({ type: "clear" });
        this._pendingAdaLog = null;
        this._assistantEntry = null;
        break;
      case "user_transcript":
        this._line.textContent = `You: ${ev.text}`;
        avcLog("you", ev.text);
        break;
      case "assistant_transcript_delta":
        this._assistantEntry = (this._assistantEntry || "") + ev.text;
        break;
      case "response_started":
        this._assistantPlaying = true;
        this._state = "speaking";
        if (this._assistantEntry) this._line.textContent = `Ada: ${this._assistantEntry}`;
        this._pendingAdaLog = this._assistantEntry || null;
        this._assistantEntry = "";
        if (this._playbackContext?.state === "suspended") this._playbackContext.resume().catch(() => {});
        this._setStatus("Ada is speaking…");
        break;
      case "response_completed":
        this._assistantPlaying = false;
        this._state = "listening";
        if (this._assistantEntry) this._line.textContent = `Ada: ${this._assistantEntry}`;
        avcLog("ada", this._pendingAdaLog || this._assistantEntry);
        this._pendingAdaLog = null;
        this._assistantEntry = null;
        this._playbackNode?.port.postMessage({ type: "flush" });
        this._setStatus("Listening");
        break;
      case "response_interrupted":
        this._assistantPlaying = false;
        this._state = "listening";
        if (this._pendingAdaLog) avcLog("ada", this._pendingAdaLog + " (interrupted)");
        this._pendingAdaLog = null;
        this._assistantEntry = null;
        this._setStatus("Listening");
        break;
      case "live_reconnecting":
        this._assistantPlaying = false;
        this._state = "reconnecting";
        this._setStatus("Reconnecting…");
        break;
      case "error":
        this._line.textContent = `Error: ${ev.message || ev.type}`;
        avcLog("error", ev.message || ev.type);
        break;
    }
    this._render();
  }

  async _connect(isRetry = false) {
    if (this._connecting || this._socket) return;
    this._connecting = true;
    if (!isRetry) this._mintRetried = false;
    this._state = "connecting";
    this._setStatus("Requesting microphone…");
    this._render();
    try {
      if (!this._apiKey()) {
        this._setStatus("Pairing this device…");
        if (!(await this._mintKey())) throw new Error("locked");
      }
      await this._createPlayback();
      await this._startMicrophone();
      const wsUrl = `${this._config.ws_url || AVC_DEFAULT_WS}`
        + `?device_id=${encodeURIComponent(this._deviceId())}`
        + `&api_key=${encodeURIComponent(this._apiKey())}`;
      this._socket = new WebSocket(wsUrl);
      this._socket.binaryType = "arraybuffer";
      this._socket.onopen = () => this._setStatus("Connecting to Ada…");
      this._socket.onmessage = (m) => {
        if (typeof m.data === "string") this._handleControl(JSON.parse(m.data));
        else this._playbackNode?.port.postMessage(m.data, [m.data]);
      };
      this._socket.onerror = () => { this._line.textContent = "WebSocket error"; };
      this._socket.onclose = async (e) => {
        if (e.code === 4401 && !this._mintRetried) {
          // Key revoked or bound to another device — re-mint and retry once.
          this._mintRetried = true;
          localStorage.removeItem(AVC_KEY_STORAGE);
          await this._teardown(false);
          this._connect(true);
          return;
        }
        if (e.code === 4401) {
          localStorage.removeItem(AVC_KEY_STORAGE);
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
        this._setStatus(err.message || "Microphone unavailable");
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
    if (this._captureNode) this._captureNode.disconnect();
    if (this._playbackMeterFrame) cancelAnimationFrame(this._playbackMeterFrame);
    this._playbackMeterFrame = null;
    this._playbackAnalyser = null;
    if (this._stream) this._stream.getTracks().forEach((t) => t.stop());
    if (this._captureContext) await this._captureContext.close().catch(() => {});
    if (this._playbackContext) await this._playbackContext.close().catch(() => {});
    this._stream = this._captureContext = this._playbackContext = this._captureNode = this._playbackNode = null;
    this._localSpeech = this._assistantPlaying = false;
    this._autoMuted = false;
    this._speechAbove = this._speechBelow = 0;
    this._noiseFloor = 0.004;
    this._assistantEntry = null;
    this._pendingAdaLog = null;
    if (this._state !== "locked" && this._state !== "error") {
      this._state = "idle";
      this._setStatus("Disconnected");
    }
    this._setLevel(0);
    this._render();
  }

  _toggle() {
    if (this._socket || this._connecting) this._teardown(true);
    else this._connect();
  }

  _toggleMute() {
    this._micMuted = !this._micMuted;
    const track = this._stream?.getAudioTracks()[0];
    if (track) track.enabled = !this._micMuted;
    this._setStatus(this._micMuted ? "Mic muted" : "Listening");
    this._render();
  }

  // ---------- ui ----------

  _setStatus(t) { if (this._status) this._status.textContent = t; avcLog("status", t); }
  _setLevel(v) { if (this._levelBar) this._levelBar.style.width = `${Math.round(v * 100)}%`; }

  _render() {
    if (!this._micBtn) return;
    const active = this._state === "listening" || this._state === "speaking";
    const busy = this._state === "connecting" || this._state === "reconnecting";
    this._micIcon.setAttribute("icon",
      this._state === "locked" ? "mdi:lock" :
      this._micMuted || this._autoMuted ? "mdi:microphone-off" :
      this._state === "speaking" ? "mdi:account-voice" :
      active ? "mdi:microphone" :
      busy ? "mdi:loading" : "mdi:microphone-outline");
    this._micBtn.style.borderColor =
      this._state === "locked" ? "var(--error-color,#f47067)" :
      this._micMuted || this._autoMuted ? "var(--error-color,#f47067)" :
      this._state === "speaking" ? "var(--primary-color,#03a9f4)" :
      active ? "var(--success-color,#4caf50)" : "var(--divider-color,#444)";
    this._micBtn.style.color =
      this._state === "locked" ? "var(--error-color,#f47067)" :
      active || busy ? "var(--primary-color,#03a9f4)" : "var(--primary-text-color)";
    this._micBtn.style.animation = busy ? "avc-pulse 1.2s ease-in-out infinite" : "";
    this._muteBtn.textContent = this._micMuted ? "Muted" : "Mute";
    this._muteBtn.style.borderColor = this._micMuted ? "var(--error-color,#f47067)" : "var(--divider-color,#444)";
    this._muteBtn.style.color = this._micMuted ? "var(--error-color,#f47067)" : "var(--primary-text-color)";
    this._autoChk.checked = this._auto;
    this._unlockRow.style.display = this._state === "locked" && !this._apiKey() ? "flex" : "none";
  }

  disconnectedCallback() { this._teardown(true); }

  getCardSize() { return 3; }
}

if (!document.getElementById("avc-style")) {
  const st = document.createElement("style");
  st.id = "avc-style";
  st.textContent = "@keyframes avc-pulse{0%,100%{opacity:1}50%{opacity:.45}}";
  document.head.appendChild(st);
}
customElements.define("ada-voice-card", AdaVoiceCard);

// ada-activity-card — log-style live feed of the voice card's activity:
// status transitions, You/Ada transcripts, errors. Renders the shared
// window channel (avcChannel); entries survive view switches, clear on
// page reload. Config: title (default "Live activity"), height (default
// calc(100vh - 380px)).
class AdaActivityCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    const card = document.createElement("ha-card");
    card.header = this._config.title || "Live activity";
    card.style.overflow = "hidden";
    this._list = document.createElement("div");
    this._list.style.cssText =
      "padding:4px 16px 14px;overflow-y:auto;font-size:.78rem;line-height:1.55;" +
      "font-family:var(--code-font-family,monospace);white-space:pre-wrap;word-break:break-word;" +
      `height:${this._config.height || "calc(100vh - 380px)"};min-height:120px`;
    card.appendChild(this._list);
    this.appendChild(card);
    this._renderAll();
  }

  connectedCallback() {
    if (!this._sub) {
      this._sub = (e) => this._append(e);
      avcChannel().subs.add(this._sub);
    }
  }

  disconnectedCallback() {
    if (this._sub) {
      avcChannel().subs.delete(this._sub);
      this._sub = null;
    }
  }

  _row(e) {
    const d = document.createElement("div");
    const ts = document.createElement("span");
    ts.style.color = "var(--secondary-text-color,#888)";
    ts.textContent = new Date(e.t).toTimeString().slice(0, 8) + "  ";
    const tag = document.createElement("span");
    const colors = {
      you: "var(--success-color,#4caf50)",
      ada: "var(--primary-color,#03a9f4)",
      status: "var(--secondary-text-color,#888)",
      error: "var(--error-color,#f47067)",
    };
    tag.style.color = colors[e.kind] || "inherit";
    if (e.kind !== "status") tag.style.fontWeight = "600";
    tag.textContent = ({ you: "You", ada: "Ada", status: "·", error: "err" }[e.kind] || e.kind) + "  ";
    const body = document.createElement("span");
    if (e.kind === "status") body.style.color = "var(--secondary-text-color,#888)";
    body.textContent = e.text;
    d.append(ts, tag, body);
    return d;
  }

  _append(e) {
    if (!this._list) return;
    const nearBottom = this._list.scrollTop + this._list.clientHeight >= this._list.scrollHeight - 40;
    this._list.appendChild(this._row(e));
    if (nearBottom) this._list.scrollTop = this._list.scrollHeight;
  }

  _renderAll() {
    if (!this._list) return;
    this._list.textContent = "";
    avcChannel().entries.forEach((e) => this._list.appendChild(this._row(e)));
    this._list.scrollTop = this._list.scrollHeight;
  }

  getCardSize() { return 4; }
}
customElements.define("ada-activity-card", AdaActivityCard);
