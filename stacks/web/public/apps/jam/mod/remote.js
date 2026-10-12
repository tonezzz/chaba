/* jam mod: remote — iPhone as the air-drum camera, Jam stays on the big
   screen. Subscribes to gesture-relay as role=screen (same fan-out the
   TV page uses): controller sends {type:"gesture", x, y, wx, wy,
   action?: pinch|fist_start|fist_end} at ~20Hz.

   Mapping (all rebindable in the matrix):
     fist_start on left half  -> hand-strike-L   (default kick)
     fist_start on right half -> hand-strike-R   (default snare)
     pinch                    -> clap
     cursor height (1 - y)    -> hand-move-<side> (note pitch)

   Play: phone opens /apps/gesture/, taps Start camera, points at self;
   this screen just listens. */
"use strict";
JAM.register("remote", {
  ws: null, retry: 0, dot: null,

  async init() {
    const d = document.createElement("div");
    d.style.cssText = "position:fixed;width:26px;height:26px;border-radius:50%;" +
      "background:radial-gradient(circle,#fbbf24,#f59e0b);border:2px solid #fff;" +
      "box-shadow:0 0 14px #f59e0b;z-index:50;display:none;pointer-events:none;" +
      "transform:translate(-50%,-50%)";
    document.body.appendChild(d);
    this.dot = d;
    this.connect();
    JAM.hud("📱 remote listening — open /apps/gesture/ on your iPhone, Start camera");
  },

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
    if (m.type !== "gesture" || m.x === undefined) return;

    const side = m.x < 0.5 ? "L" : "R";
    if (this.dot) {
      this.dot.style.display = "block";
      this.dot.style.left = (m.x * innerWidth) + "px";
      this.dot.style.top = (m.y * innerHeight) + "px";
    }
    if (m.action === "fist_start") {
      JAM.emit(`hand-strike-${side}`, 1);
      JAM.hud(`📱 fist ${side === "L" ? "left" : "right"} → strike`);
    } else if (m.action === "pinch") {
      JAM.emit("clap", 1);
      JAM.hud("📱 pinch → clap");
    } else {
      JAM.emit(`hand-move-${side}`, Math.max(0, Math.min(1, 1 - m.y)));
    }
  },

  destroy() {
    const ws = this.ws; this.ws = null;   // null first so onclose won't reconnect
    ws && ws.close();
    this.dot && this.dot.remove(); this.dot = null;
  },
});
