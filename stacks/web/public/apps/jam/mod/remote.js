/* jam mod: remote — iPhone as the air-drum camera, Jam stays on the big
   screen. Subscribes to gesture-relay as role=screen (same fan-out the
   TV page uses). Controller sends per-hand frames:
     {type:"gesture", hand:"Left"|"Right"?, x, y, wx, wy,
      action?: pinch|fist_start|fist_end}  at ~20Hz.

   Mapping (zones painted on screen, all rebindable in the matrix):
     fist in left half  -> hand-strike-L   (default kick)
     fist in right half -> hand-strike-R   (default snare)
     pinch (either hand)-> clap
     hand height (1-y)  -> hand-move-<side> (note pitch)

   Play: phone opens /apps/gesture/, taps Start camera, points at self;
   this screen just listens. Two hands tracked -> both can strike. */
"use strict";
JAM.register("remote", {
  ws: null, retry: 0, dots: {}, zones: null, zoneSig: "",
  steps: {}, lastSeen: {}, lastEmit: {}, glideWd: 0, vx: null,

  // iPhone mic -> relay -> here. Random rotating sci-fi chain:
  // ring-mod + feedback delay + playback-rate wobble, preset swaps ~1.2s.
  SCIFI: [
    { name: "🤖 robot",     ring: 45,  rate: 1.0,  del: 0.18, wet: 0.6, dry: 0.4 },
    { name: "👾 dalek",     ring: 65,  rate: 0.85, del: 0.24, wet: 0.7, dry: 0.3 },
    { name: "🐿 chipmunk",  ring: 0,   rate: 1.55, del: 0.10, wet: 0.4, dry: 0.7 },
    { name: "🌌 deep space",ring: 24,  rate: 0.72, del: 0.42, wet: 0.7, dry: 0.5 },
    { name: "🛸 martian",   ring: 110, rate: 1.25, del: 0.15, wet: 0.6, dry: 0.4 },
  ],

  voiceChain() {
    if (this.vx) return this.vx;
    const ac = JAM._actx();
    const input = ac.createGain(); input.gain.value = 0.9;
    const ring = ac.createGain(); ring.gain.value = 0;
    const carrier = ac.createOscillator(); carrier.frequency.value = 45;
    carrier.connect(ring.gain); carrier.start();
    const dry = ac.createGain(), wet = ac.createGain();
    const delay = ac.createDelay(1), fb = ac.createGain();
    delay.delayTime.value = 0.22; fb.gain.value = 0.35;
    const lp = ac.createBiquadFilter();
    lp.type = "lowpass"; lp.frequency.value = 3200; lp.Q.value = 0.5;
    input.connect(ring); input.connect(dry);
    ring.connect(wet); ring.connect(delay);
    delay.connect(fb).connect(delay); delay.connect(wet);
    dry.connect(lp); wet.connect(lp); lp.connect(ac.destination);
    this.vx = { input, carrier, dry, wet, delay, preset: -1, swapT: 0, next: 0 };
    return this.vx;
  },

  voice(m) {
    const ac = JAM._actx(), vx = this.voiceChain();
    // rotate the sci-fi preset on a timer — keeps it surprising
    const now = performance.now();
    if (now > vx.swapT) {
      vx.swapT = now + 1200;
      vx.preset = (vx.preset + 1 + (Math.random() * (this.SCIFI.length - 1) | 0))
                  % this.SCIFI.length;
      const p = this.SCIFI[vx.preset];
      vx.carrier.frequency.value = Math.max(0.01, p.ring);
      vx.rate = p.rate;
      vx.wet.gain.value = p.ring ? p.wet : 0;
      vx.dry.gain.value = p.dry;
      vx.delay.delayTime.value = p.del;
      JAM.hud(`🎙 sci-fi voice → ${p.name}`);
    }
    const bin = atob(m.pcm), n = bin.length >> 1;
    const buf = ac.createBuffer(1, n, m.sr || 12000);
    const f32 = buf.getChannelData(0);
    for (let i = 0; i < n; i++)
      f32[i] = ((bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8)) << 16 >> 16) / 32768;
    const src = ac.createBufferSource();
    src.buffer = buf; src.playbackRate.value = vx.rate || 1;
    src.connect(vx.input);
    // clamp drift: silence gaps / bursts must not stack into the future
    if (vx.next < ac.currentTime || vx.next > ac.currentTime + 0.4)
      vx.next = ac.currentTime + 0.03;
    const t = vx.next;
    src.start(t);
    vx.next = t + buf.duration / (vx.rate || 1);
  },

  async init() {
    // per-hand cursors: L amber / R cyan; single-hand senders share "?"
    for (const [k, c] of [["L", "#fbbf24"], ["R", "#22d3ee"], ["?", "#a78bfa"]]) {
      const d = document.createElement("div");
      d.style.cssText = "position:fixed;width:26px;height:26px;border-radius:50%;" +
        `background:radial-gradient(circle,${c},${c});border:2px solid #fff;` +
        `box-shadow:0 0 14px ${c};z-index:50;display:none;pointer-events:none;` +
        "transform:translate(-50%,-50%)";
      document.body.appendChild(d);
      this.dots[k] = d;
    }

    // instrument zone overlay — translucent halves labeled with the
    // CURRENT bindings so "where to move" is always true
    const z = document.createElement("div");
    z.style.cssText = "position:fixed;inset:0;z-index:40;pointer-events:none;display:flex";
    for (const s of ["L", "R"]) {
      const half = document.createElement("div");
      half.style.cssText = "flex:1;margin:8px;border:2px dashed rgba(148,163,184,.3);" +
        "border-radius:14px;display:flex;align-items:flex-end;justify-content:center";
      const tag = document.createElement("span");
      tag.dataset.zone = s;
      tag.style.cssText = "font:700 15px ui-monospace,monospace;color:#e5e7eb;" +
        "background:rgba(2,6,23,.72);padding:6px 14px;border-radius:9px;margin:12px";
      half.appendChild(tag);
      z.appendChild(half);
    }
    document.body.appendChild(z);
    this.zones = z;
    this.paintZones();

    // theremin watchdog: hand out of frame ~350ms -> tone fades out
    this.glideWd = setInterval(() => {
      const now = performance.now(), ac = JAM._actx();
      for (const s of ["L", "R"]) {
        if (!this.lastSeen[s]) continue;
        const v = JAM._tone("remote-" + s);
        if (v.g.gain.value > 0.01 && now - this.lastSeen[s] > 350)
          v.g.gain.setTargetAtTime(0, ac.currentTime, 0.12);
      }
    }, 200);

    this.connect();
    JAM.hud("📱 remote listening — /apps/gesture/ on iPhone, Start camera");
  },

  paintZones() {
    if (!this.zones) return;
    const sig = JSON.stringify([this.JAM_BIND("hand-strike-L"),
                                this.JAM_BIND("hand-strike-R")]);
    if (sig === this.zoneSig) return;
    this.zoneSig = sig;
    this.zones.querySelector('[data-zone="L"]').textContent =
      `✊ ${this.JAM_BIND("hand-strike-L") || "—"}  ·  ⬆ higher note`;
    this.zones.querySelector('[data-zone="R"]').textContent =
      `✊ ${this.JAM_BIND("hand-strike-R") || "—"}  ·  ⬆ higher note`;
  },
  JAM_BIND(evt) { return JAM.bindings[evt]; },

  connect() {
    const ws = new WebSocket(
      `${location.protocol === "https:" ? "wss" : "ws"}://` +
      `${location.host}/apps/gesture-live/ws?role=screen`);
    this.ws = ws;
    ws.onopen = () => { this.retry = 0; JAM.hud("📱 remote linked — waiting for iPhone controller"); };
    ws.onclose = ws.onerror = () => {
      JAM.hud("📱 relay offline — retrying");
      setTimeout(() => this.ws && this.connect(),
                 Math.min(8000, 500 * 2 ** this.retry++));
    };
    ws.onmessage = ev => this.onMsg(ev.data);
  },

  onMsg(data) {
    let m; try { m = JSON.parse(data); } catch { return; }
    if (m.type === "peer") return;
    if (m.type === "voice" && m.pcm) { this.voice(m); return; }
    // face/pose events ride as {type:"body", evt, val} — straight to the bus
    if (m.type === "body" && m.evt) {
      const now = performance.now();          // screen-side retrigger guard
      if (now - (this.lastBody?.[m.evt] || 0) < 250 &&
          !m.evt.startsWith("swipe") && m.evt !== "lean") return;
      (this.lastBody ||= {})[m.evt] = now;
      JAM.emit(m.evt, m.val ?? 1);
      JAM.hud(`📱 ${m.evt} → ${JAM.bindings[m.evt] || "—"}`);
      return;
    }
    if (m.type !== "gesture" || m.x === undefined) return;

    // zones are positional: which half the strike lands in picks the drum.
    // hand label (when sent) only picks the cursor color.
    const side = m.x < 0.5 ? "L" : "R";
    const key = m.hand ? m.hand[0] : "?";
    const dot = this.dots[key] || this.dots["?"];
    if (dot) {
      dot.style.display = "block";
      dot.style.left = (m.x * innerWidth) + "px";
      dot.style.top = (m.y * innerHeight) + "px";
    }

    if (m.action === "fist_start") {
      JAM.emit(`hand-strike-${side}`, 1);
      JAM.hud(`📱 fist ${side === "L" ? "left" : "right"} zone → ${JAM.bindings[`hand-strike-${side}`] || "strike"}`);
    } else if (m.action === "pinch") {
      JAM.emit("clap", 1);
      JAM.hud("📱 pinch → " + (JAM.bindings["clap"] || "clap"));
    } else {
      // theremin: ONE sustained tone per side, pitch glides with height.
      // Hand presence = sound, never a note stream — cannot machine-gun.
      const ac = JAM._actx(), now = performance.now();
      const tone = JAM._tone("remote-" + side, side === "L" ? "sine" : "triangle");
      const scale = JAM._SCALES.blue;
      const deg = Math.min(7, Math.max(0, ((1 - m.y) * 8) | 0));
      tone.o.frequency.setTargetAtTime(
        JAM._NOTE((side === "L" ? 50 : 38) +
                  scale[deg % scale.length] + 12 * (deg / scale.length | 0)),
        ac.currentTime, 0.07);
      tone.g.gain.setTargetAtTime(0.12, ac.currentTime, 0.08);
      this.lastSeen[side] = now;
      // real movement -> energy for the band (unbound by default);
      // capped ~4/s so a held hand can't pin the band at full tilt
      if (deg !== (this.steps[side] ?? -1) &&
          now - (this.lastEmit[side] || 0) > 250) {
        this.steps[side] = deg;
        this.lastEmit[side] = now;
        JAM.emit(`hand-move-${side}`, deg / 7);
      }
    }
    this.paintZones();
  },

  destroy() {
    const ws = this.ws; this.ws = null;   // null first so onclose won't reconnect
    ws && ws.close();
    for (const k in this.dots) this.dots[k].remove();
    this.dots = {};
    this.zones && this.zones.remove(); this.zones = null; this.zoneSig = "";
    if (this.vx) { try { this.vx.carrier.stop(); } catch {} this.vx = null; }
    clearInterval(this.glideWd);
    JAM._toneDrop("remote-L"); JAM._toneDrop("remote-R");
    this.steps = {}; this.lastSeen = {}; this.lastEmit = {};
  },
});
