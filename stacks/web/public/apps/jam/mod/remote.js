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
    if (m.type === "peer" || m.type !== "gesture" || m.x === undefined) return;

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
      JAM.emit(`hand-move-${side}`, Math.max(0, Math.min(1, 1 - m.y)));
    }
    this.paintZones();
  },

  destroy() {
    const ws = this.ws; this.ws = null;   // null first so onclose won't reconnect
    ws && ws.close();
    for (const k in this.dots) this.dots[k].remove();
    this.dots = {};
    this.zones && this.zones.remove(); this.zones = null; this.zoneSig = "";
  },
});
