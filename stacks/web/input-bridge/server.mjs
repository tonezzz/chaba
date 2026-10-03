#!/usr/bin/env node
"use strict";

import http from "node:http";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { WebSocketServer } from "ws";

const PORT = parseInt(process.env.INPUT_BRIDGE_PORT || "3010", 10);
// Default 0.0.0.0 is fine on a home host (LAN+tailnet). On idc01 (public VPS)
// set INPUT_BRIDGE_BIND=100.74.146.0 so the relay never touches the public
// interface — /pub and /claim have no listener auth of their own.
const BIND = process.env.INPUT_BRIDGE_BIND || "0.0.0.0";
const PING_INTERVAL_MS = 30000;
const PENDING_TTL_MS = parseInt(process.env.VCAST_PENDING_TTL_MS || "300000", 10);
const ADA_AUTH_URL = (process.env.ADA_AUTH_URL || "").replace(/\/+$/, "");
const ADA_ADMIN_KEY = process.env.ADA_ADMIN_KEY || "";
const REGISTRY_FILE =
  process.env.VCAST_REGISTRY ||
  path.join(os.homedir(), ".local", "share", "input-bridge", "displays.json");
const REDEEM_HOSTS = new Set(
  (process.env.VCAST_REDEEM_HOSTS ||
    "idc01.taila0626a.ts.net,tony-dell.taila0626a.ts.net,mn01.taila0626a.ts.net"
  ).split(",")
);

// ---------------------------------------------------------------------------
// Screen registry (vcast virtual displays) — name -> screen number, persisted.
// ---------------------------------------------------------------------------
const registry = { screens: {} };
const live = new Map(); // screen number -> ws
const pending = new Map(); // sid -> {ws, label, ts}

function loadRegistry() {
  try {
    const data = JSON.parse(fs.readFileSync(REGISTRY_FILE, "utf8"));
    if (data && typeof data.screens === "object") registry.screens = data.screens;
  } catch (e) { /* fresh registry */ }
}

function saveRegistry() {
  try {
    fs.mkdirSync(path.dirname(REGISTRY_FILE), { recursive: true });
    fs.writeFileSync(REGISTRY_FILE, JSON.stringify(registry, null, 2));
  } catch (e) {
    console.error("[input-bridge] registry save failed:", e.message);
  }
}

function allocScreen(name) {
  for (const [n, s] of Object.entries(registry.screens)) {
    if (s.name === name) return parseInt(n, 10);
  }
  const used = new Set(Object.keys(registry.screens).map((n) => parseInt(n, 10)));
  let n = 1;
  while (used.has(n)) n++;
  registry.screens[n] = { name, assigned_at: new Date().toISOString() };
  saveRegistry();
  return n;
}

function releaseScreenByWs(ws) {
  if (ws.screen == null) return;
  live.delete(ws.screen);
  ws.screen = null;
}

function pendingCleanup() {
  const now = Date.now();
  for (const [sid, p] of pending) {
    if (now - p.ts > PENDING_TTL_MS || !p.ws || p.ws.readyState !== 1) {
      pending.delete(sid);
    }
  }
}

// ---------------------------------------------------------------------------
// Ada backend helpers (server-side: no browser CORS issues)
// ---------------------------------------------------------------------------
async function adaFetch(pathname, opts = {}) {
  if (!ADA_AUTH_URL) return null;
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), 5000);
  try {
    return await fetch(ADA_AUTH_URL + pathname, { ...opts, signal: ctrl.signal });
  } finally {
    clearTimeout(t);
  }
}

async function adaKeyName(apiKey) {
  const res = await adaFetch(
    `/api/auth/status?api_key=${encodeURIComponent(apiKey)}`
  );
  if (!res || !res.ok) return null;
  const data = await res.json().catch(() => ({}));
  return data && data.authenticated ? data.name : null;
}

async function adaCreateScreenKey(adminKey, name) {
  const res = await adaFetch("/api/auth/keys", {
    method: "POST",
    headers: { "content-type": "application/json", "x-api-key": adminKey },
    body: JSON.stringify({ name, path: "/", redirect: "/apps/vcast" }),
  });
  if (res && res.status === 409) return { conflict: true };
  if (!res || !res.ok) return { error: `ada keys POST -> ${res ? res.status : "unreachable"}` };
  return await res.json().catch(() => ({ error: "bad ada keys response" }));
}

async function adaRevokeKey(adminKey, name) {
  const res = await adaFetch(`/api/auth/keys/${encodeURIComponent(name)}`, {
    method: "DELETE",
    headers: { "x-api-key": adminKey },
  });
  return !!(res && res.ok);
}

async function redeemKey(redeemUrl) {
  // redeem_url is a path like /redeem/<token> on the ada origin. Burn it
  // server-side and pull the api_key out of the 302 Location header.
  let url;
  try {
    url = new URL(redeemUrl, ADA_AUTH_URL);
  } catch (e) {
    return { error: "bad redeem url" };
  }
  if (!REDEEM_HOSTS.has(url.hostname)) {
    return { error: `redeem host ${url.hostname} not allowed` };
  }
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), 8000);
  let res;
  try {
    res = await fetch(url, { redirect: "manual", signal: ctrl.signal });
  } finally {
    clearTimeout(t);
  }
  const loc = res.headers.get("location") || "";
  const m = loc.match(/[?&]api_key=([^&]+)/);
  if (!m) return { error: `redeem failed (${res.status})` };
  return { api_key: decodeURIComponent(m[1]) };
}

// ---------------------------------------------------------------------------
// HTTP API
// ---------------------------------------------------------------------------

// Keyless claim/release/dismiss is only trusted from the tailnet (CGNAT
// 100.64.0.0/10) or loopback. A LAN client (plain-http edge like
// http://192.168.2.67) must supply body.admin_key, which is verified against
// ada as before. The tailnet client IP is the FIRST X-Forwarded-For entry —
// tailscale serve and Caddy both append, so the leftmost hop is the real peer.
function clientIp(req) {
  const xff = String(req.headers["x-forwarded-for"] || "").split(",")[0].trim();
  return xff || req.socket.remoteAddress || "";
}
function tailnetClient(req) {
  let ip = clientIp(req).replace(/^::ffff:/, "");
  if (ip === "127.0.0.1" || ip === "::1") return true;
  const m = ip.match(/^100\.(\d{1,3})\./);
  return !!m && +m[1] >= 64 && +m[1] <= 127;
}
// GET /img allowlist — tailnet hostnames and private/loopback address space.
function imgProxyAllowed(u) {
  let h;
  try {
    h = new URL(u).hostname;
  } catch (e) {
    return false;
  }
  if (/^[^.]+\.taila0626a\.ts\.net$/i.test(h) || h === "localhost" ||
      h.endsWith(".local") || h.endsWith(".lan")) return true;
  const m = h.replace(/^::ffff:/, "").match(/^(\d+)\.(\d+)\.\d+\.\d+$/);
  if (!m) return false;
  const a = +m[1], b = +m[2];
  if (a === 10 || a === 127 || (a === 100 && b >= 64 && b <= 127)) return true;
  if (a === 192 && b === 168) return true;
  if (a === 172 && b >= 16 && b <= 31) return true;
  return false;
}

function json(res, code, obj) {
  res.writeHead(code, {
    "content-type": "application/json",
    // tailnet-only service; the HA card calls these cross-origin from :8123
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "GET, POST, OPTIONS",
    "access-control-allow-headers": "content-type",
  });
  res.end(JSON.stringify(obj));
}

function readBody(req, limit = 65536) {
  return new Promise((resolve, reject) => {
    let data = "";
    req.on("data", (c) => {
      data += c;
      if (data.length > limit) {
        req.destroy();
        reject(new Error("body too large"));
      }
    });
    req.on("end", () => {
      try {
        resolve(JSON.parse(data || "{}"));
      } catch (e) {
        reject(new Error("invalid json"));
      }
    });
    req.on("error", reject);
  });
}

function displaysSnapshot() {
  pendingCleanup();
  const screens = Object.entries(registry.screens).map(([n, s]) => {
    const ws = live.get(parseInt(n, 10));
    return {
      screen: parseInt(n, 10),
      name: s.name,
      label: s.label || s.name,
      assigned_at: s.assigned_at,
      connected: !!(ws && ws.readyState === 1),
      last_seen: s.last_seen || null,
      state: s.state || "idle",
      state_detail: s.state_detail || null,
      panes: s.panes || 1,
    };
  });
  screens.sort((a, b) => a.screen - b.screen);
  return {
    screens,
    pending: [...pending.entries()].map(([sid, p]) => ({
      sid,
      label: p.label || null,
      since: new Date(p.ts).toISOString(),
    })),
  };
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://x");

  if (req.method === "OPTIONS") {
    return json(res, 204, {});
  }

  if (req.method === "GET" && url.pathname === "/health") {
    return json(res, 200, {
      ok: true,
      rooms: rooms.size,
      screens: Object.keys(registry.screens).length,
      ada_auth: !!ADA_AUTH_URL,
    });
  }

  if (req.method === "GET" && url.pathname === "/displays") {
    return json(res, 200, displaysSnapshot());
  }

  // Capture leases: {screen -> {source, ch?, active, since, by}} — ground
  // truth for "is a camera capture running on this screen" so Ada asks
  // permission before starting/stopping (camera_cast_permission contract).
  // Writers: vcast page (uplink), Ada cast/cctv tools.
  if (req.method === "GET" && url.pathname === "/capture") {
    const screen = url.searchParams.get("screen");
    if (screen != null) {
      return json(res, 200, captureState[screen] || { active: false });
    }
    const active = Object.fromEntries(
      Object.entries(captureState).filter(([, c]) => c.active));
    return json(res, 200, { captures: active });
  }

  if (req.method === "POST" && url.pathname === "/capture") {
    let body;
    try {
      body = await readBody(req);
    } catch (e) {
      return json(res, 400, { error: e.message });
    }
    const screen = Number(body.screen);
    if (!Number.isInteger(screen) || screen < 0)
      return json(res, 400, { error: "screen required" });
    if (body.active === false) {
      delete captureState[screen];
      return json(res, 200, { ok: true, active: false });
    }
    captureState[screen] = {
      active: true,
      source: String(body.source || "cam"),
      ch: body.ch ? String(body.ch).slice(0, 80) : null,
      by: body.by ? String(body.by).slice(0, 80) : "display",
      since: new Date().toISOString(),
    };
    return json(res, 200, { ok: true, capture: captureState[screen] });
  }

  // Cam-wall control: {zones: {<zone>: {enabled, screen, since}}} — the
  // puller on tony-dell GETs this each cycle; Ada's cctv_wall tool POSTs it.
  if (req.method === "GET" && url.pathname === "/camwall") {
    return json(res, 200, camwallState);
  }

  if (req.method === "POST" && url.pathname === "/camwall") {
    let body;
    try {
      body = await readBody(req);
    } catch (e) {
      return json(res, 400, { error: e.message });
    }
    const zone = String(body.zone || "");
    if (!zone) return json(res, 400, { error: "zone required" });
    const cur = camwallState.zones[zone] || {};
    if (body.enabled === false) {
      // disable refresh but KEEP settings — re-enabling restores the knobs;
      // zones with no saved settings are dropped entirely
      if (cur.settings) camwallState.zones[zone] = { ...cur, enabled: false };
      else delete camwallState.zones[zone];
    } else {
      camwallState.zones[zone] = {
        ...cur,
        enabled: body.enabled != null ? !!body.enabled
                                    : cur.enabled ?? true,
        // explicit null unbinds the zone from its screen (stale-binding
        // cleanup); omitting screen keeps the current binding
        screen: "screen" in body
                ? (body.screen == null ? null : Number(body.screen))
                : cur.screen ?? null,
        since: cur.enabled && body.enabled == null
               ? cur.since : new Date().toISOString(),
      };
    }
    // settings knobs — merged shallowly; the puller validates/uses:
    // {interval, jpeg_q, thumb_w, cams_skip[], cams_extra[], effects[]}
    if (body.settings && typeof body.settings === "object") {
      const KNOWN = new Set(["interval", "jpeg_q", "thumb_w",
                             "thumb_frac",
                             "cams_skip", "cams_extra", "effects"]);
      const clean = {};
      for (const [k, v] of Object.entries(body.settings)) {
        if (!KNOWN.has(k)) continue;               // drop stray keys
        if (k === "cams_extra" && Array.isArray(v)) {
          clean[k] = v.filter(c =>
            c && typeof c === "object" && c.label && c.url && c.kind);
          continue;
        }
        clean[k] = v;
      }
      camwallState.zones[zone].settings = {
        ...(camwallState.zones[zone].settings || {}),
        ...clean,
      };
    }
    saveCamwall();
    return json(res, 200, { ok: true, zones: camwallState.zones });
  }

  if (req.method === "GET" && url.pathname === "/pair-info") {
    const sid = url.searchParams.get("sid") || "";
    const p = pending.get(sid);
    if (!p) return json(res, 404, { error: "unknown or expired sid" });
    return json(res, 200, {
      sid,
      label: p.label || null,
      since: new Date(p.ts).toISOString(),
    });
  }

  if (req.method === "POST" && url.pathname === "/pub") {
    let body;
    try {
      body = await readBody(req);
    } catch (e) {
      return json(res, 400, { error: e.message });
    }
    const msg = body.msg;
    if (!msg || typeof msg !== "object") return json(res, 400, { error: "msg required" });
    let room = body.room;
    if (body.screen != null) room = `vcast-${body.screen}`;
    if (!room) return json(res, 400, { error: "screen or room required" });
    const delivered = broadcastTo(room, msg);
    return json(res, 200, { ok: true, room, delivered });
  }

  // Display self-snapshot: a vcast page answers a ws "snap-request" by
  // POSTing {screen, token, data(dataURL), state, error?} here; tools poll
  // GET /frame?screen=N&token=T for the latest capture. Frames are kept
  // in memory only — latest-wins per screen, lost on restart.
  if (req.method === "POST" && url.pathname === "/frame") {
    let body;
    try {
      body = await readBody(req, 12 * 1024 * 1024);
    } catch (e) {
      return json(res, 400, { error: e.message });
    }
    const screen = Number(body.screen);
    if (!Number.isInteger(screen) || screen < 0)
      return json(res, 400, { error: "screen required" });
    // screen 0 = shared asset bucket (cam-snap casts); screens N>=1 are
    // the display's own captures
    const token = body.token ? String(body.token).slice(0, 80) : "snap";
    const raw = String(body.data || "");
    const b64 = raw.includes(",") ? raw.slice(raw.indexOf(",") + 1) : raw;
    const buf = b64 ? Buffer.from(b64, "base64") : null;
    lastFrames.set(`${screen}:${token}`, {
      ts: Date.now(),
      state: String(body.state || ""),
      error: body.error ? String(body.error).slice(0, 300) : null,
      detail: body.detail ? String(body.detail).slice(0, 300) : null,
      diag: body.diag ? String(body.diag).slice(0, 300) : null,
      buf,
    });
    if (lastFrames.size > 64) {  // bound memory — drop oldest
      const oldest = lastFrames.keys().next().value;
      lastFrames.delete(oldest);
    }
    return json(res, 200, { ok: true, bytes: buf ? buf.length : 0 });
  }

  if (req.method === "GET" && url.pathname === "/frame") {
    const screen = Number(url.searchParams.get("screen"));
    const token = url.searchParams.get("token");
    const f = lastFrames.get(`${screen}:${token || ""}`)
        || (token ? null : [...lastFrames.entries()]
             .filter(([k]) => k.startsWith(`${screen}:`))
             .sort((a, b) => b[1].ts - a[1].ts)[0]?.[1]);
    if (!f) {
      return json(res, 404, {
        error: "frame not ready", screen,
        state: f ? f.state : null,
      });
    }
    if (f.error || !f.buf) {
      return json(res, 200, {
        ok: true, screen, state: f.state,
        error: f.error || "no image data",
        detail: f.detail || null,
        diag: f.diag || null,
      });
    }
    // sniff real type — iOS Safari can refuse a PNG body under image/jpeg;
    // RIFF/WAVE = backend-TTS narration audio for the speak fallback
    const b = f.buf;
    const ct =
        b.length > 4 && b[0] === 0x89 && b[1] === 0x50 ? "image/png"
      : b.length > 11 && b[0] === 0x52 && b[1] === 0x49 && b[2] === 0x46
        && b[8] === 0x57 && b[9] === 0x41 && b[10] === 0x56 ? "audio/wav"
      : "image/jpeg";
    res.writeHead(200, { "content-type": ct, "cache-control": "no-store" });
    return res.end(f.buf);
  }

  // Same-origin image proxy for snapFrame's tainted-canvas fallback: when a
  // casted <img> came from a cross-origin host without CORS, the display can
  // see it but can't read pixels back. It asks us to refetch the URL
  // server-side and reloads the blob — same-origin, so canvas stays clean.
  // Allowlisted to tailnet/LAN/loopback so this can't be an open proxy.
  if (req.method === "GET" && url.pathname === "/img") {
    const target = url.searchParams.get("url") || "";
    if (!/^https?:\/\//i.test(target) || !imgProxyAllowed(target)) {
      return json(res, 403, { error: "url not allowed" });
    }
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 10000);
    let up;
    try {
      up = await fetch(target, { redirect: "follow", signal: ctrl.signal });
    } catch (e) {
      clearTimeout(t);
      return json(res, 502, { error: String(e.message || e) });
    }
    clearTimeout(t);
    if (!up.ok) return json(res, 502, { error: `upstream ${up.status}` });
    const len = Number(up.headers.get("content-length") || 0);
    if (len > 20 * 1024 * 1024) return json(res, 413, { error: "too large" });
    const buf = Buffer.from(await up.arrayBuffer());
    if (buf.length > 20 * 1024 * 1024) return json(res, 413, { error: "too large" });
    res.writeHead(200, {
      "content-type": up.headers.get("content-type") || "application/octet-stream",
      "access-control-allow-origin": "*",
      "cache-control": "no-store",
    });
    return res.end(buf);
  }

  if (req.method === "POST" && url.pathname === "/claim") {
    // Pairing a pending display: admin key authorizes, ada backend issues a
    // screen key, the redeem URL is burned server-side, and the api_key is
    // pushed to the waiting display over its pending websocket.
    let body;
    try {
      body = await readBody(req);
    } catch (e) {
      return json(res, 400, { error: e.message });
    }
    const { sid, force } = body;
    if (!sid || !pending.has(sid)) {
      return json(res, 404, { error: "unknown or expired sid" });
    }
    if (!body.admin_key && !tailnetClient(req)) {
      return json(res, 403, { error: "admin key required off-tailnet" });
    }
    const admin_key = body.admin_key || ADA_ADMIN_KEY;
    if (!admin_key) return json(res, 403, { error: "no admin key configured" });
    const adminName = await adaKeyName(admin_key).catch(() => null);
    if (!adminName) return json(res, 403, { error: "admin key not accepted" });

    let name = String(body.name || "").trim();
    const wanted = parseInt((name.match(/^screen-(\d+)$/) || [])[1] || "0", 10);
    if (!name || wanted) {
      // allocate: reuse the requested number when free, else lowest free
      const used = new Set(Object.keys(registry.screens).map((n) => parseInt(n, 10)));
      let n = wanted;
      if (!n || used.has(n)) {
        n = 1;
        while (used.has(n)) n++;
      }
      name = `screen-${n}`;
    }

    if (force) await adaRevokeKey(admin_key, name);
    const created = await adaCreateScreenKey(admin_key, name);
    if (created.conflict) {
      return json(res, 409, { error: `name ${name} already issued`, name });
    }
    if (created.error) return json(res, 502, { error: created.error });

    const redeemed = await redeemKey(created.redeem_url);
    if (redeemed.error) return json(res, 502, { error: redeemed.error });

    let screen = allocScreen(name);
    // honor an explicit screen-N request: allocScreen() picks the lowest
    // free slot which may differ from the wanted number — move the entry
    // so "claim screen-4" actually lands on 4 (2026-09-30: headless test
    // displays kept drifting to whatever slot freed first)
    if (wanted && wanted !== screen && !registry.screens[wanted]) {
      registry.screens[wanted] = registry.screens[screen];
      delete registry.screens[screen];
      screen = wanted;
    }
    registry.screens[screen].label = pending.get(sid)?.label || name;
    saveRegistry();

    const p = pending.get(sid);
    if (p && p.ws && p.ws.readyState === 1) {
      p.ws.send(
        JSON.stringify({
          type: "paired",
          api_key: redeemed.api_key,
          name,
          screen,
        })
      );
    }
    pending.delete(sid);
    return json(res, 200, { ok: true, screen, name });
  }

  if (req.method === "POST" && url.pathname === "/release") {
    // Revoke a screen: delete the ada key, drop the registry entry, tell the
    // display to fall back to the pairing QR.
    let body;
    try {
      body = await readBody(req);
    } catch (e) {
      return json(res, 400, { error: e.message });
    }
    if (!body.admin_key && !tailnetClient(req)) {
      return json(res, 403, { error: "admin key required off-tailnet" });
    }
    const admin_key = body.admin_key || ADA_ADMIN_KEY;
    if (!admin_key) return json(res, 403, { error: "no admin key configured" });
    const adminName = await adaKeyName(admin_key).catch(() => null);
    if (!adminName) return json(res, 403, { error: "admin key not accepted" });

    const n = body.screen != null ? parseInt(body.screen, 10) : null;
    const key = n != null ? String(n) : null;
    let name = body.name ? String(body.name) : null;
    if (!name && key && registry.screens[key]) name = registry.screens[key].name;
    if (!name) return json(res, 404, { error: "unknown screen" });

    const revoked = await adaRevokeKey(admin_key, name);
    const entry = Object.entries(registry.screens).find(([, s]) => s.name === name);
    if (entry) {
      const num = parseInt(entry[0], 10);
      const ws = live.get(num);
      if (ws) {
        if (ws.readyState === 1) ws.send(JSON.stringify({ type: "unpaired" }));
        // detach now — the stale socket's later close would otherwise
        // evict a re-registered display from live[]
        ws.screen = null;
        live.delete(num);
      }
      delete registry.screens[entry[0]];
      saveRegistry();
    }
    return json(res, 200, { ok: true, name, revoked });
  }

  if (req.method === "POST" && url.pathname === "/dismiss") {
    // Drop a pending (unclaimed) display — the "revoke" for waiting rows.
    let body;
    try {
      body = await readBody(req);
    } catch (e) {
      return json(res, 400, { error: e.message });
    }
    if (!body.admin_key && !tailnetClient(req)) {
      return json(res, 403, { error: "admin key required off-tailnet" });
    }
    const p = pending.get(body.sid);
    if (!p) return json(res, 404, { error: "unknown or expired sid" });
    pending.delete(body.sid);
    if (p.ws && p.ws.readyState === 1) {
      p.ws.pendingSid = null;
      p.ws.send(JSON.stringify({ type: "dismissed" }));
    }
    return json(res, 200, { ok: true });
  }

  json(res, 404, { error: "not found" });
});

// ---------------------------------------------------------------------------
// WebSocket relay
// ---------------------------------------------------------------------------
const rooms = new Map();
const lastFrames = new Map(); // "screen:token" -> {ts, state, error, detail, buf}
const lastCast = new Map();   // "room|pane" -> last play/image/nav/stop/layout
                              // msg (replayed to a display on register so a ws
                              // flap doesn't blank the screen; pane-keyed so
                              // split layouts restore every pane)
// Cam-wall zone state — persisted so enable flags AND settings knobs
// (interval/quality/effects/cams) survive a bridge restart.
const CAMWALL_FILE =
  process.env.VCAST_CAMWALL ||
  path.join(os.homedir(), ".local", "share", "input-bridge", "camwall.json");
const camwallState = { zones: {} };

function loadCamwall() {
  try {
    const data = JSON.parse(fs.readFileSync(CAMWALL_FILE, "utf8"));
    if (data && typeof data.zones === "object") camwallState.zones = data.zones;
  } catch (e) { /* fresh state */ }
}
function saveCamwall() {
  try {
    fs.mkdirSync(path.dirname(CAMWALL_FILE), { recursive: true });
    fs.writeFileSync(CAMWALL_FILE, JSON.stringify(camwallState, null, 2));
  } catch (e) {
    console.error("[input-bridge] camwall save failed:", e.message);
  }
}
loadCamwall();
const captureState = {}; // screen -> {source, ch, active, since, by} — capture leases

function leaveRoom(ws) {
  const room = ws.room;
  if (!room || !rooms.has(room)) return;
  const clients = rooms.get(room);
  clients.delete(ws);
  if (clients.size === 0) rooms.delete(room);
  ws.room = null;
}

function joinRoom(ws, room) {
  leaveRoom(ws);
  room = String(room || "default");
  ws.room = room;
  if (!rooms.has(room)) rooms.set(room, new Set());
  rooms.get(room).add(ws);
}

function broadcastTo(room, data) {
  const clients = rooms.get(room);
  if (!clients) return 0;
  const msg = typeof data === "string" ? data : JSON.stringify(data);
  // remember display-state casts so a reconnecting screen re-renders instead
  // of going idle after a ws flap
  try {
    const obj = typeof data === "string" ? JSON.parse(data) : data;
    if (["play", "image", "nav", "stop", "layout", "zoom"].includes(obj?.type)) {
      const pane = obj.pane ?? "";
      // layout/stop reshape the whole screen — flush older pane state
      if (obj.type === "layout" || (obj.type === "stop" && pane === "")) {
        for (const k of [...lastCast.keys()])
          if (k.startsWith(room + "|")) lastCast.delete(k);
      }
      lastCast.set(`${room}|${pane}`, obj);
    }
  } catch (e) { /* ignore */ }
  let delivered = 0;
  for (const client of clients) {
    if (client.readyState === 1) {
      client.send(msg);
      delivered++;
    }
  }
  return delivered;
}

function broadcast(ws, data) {
  const room = ws.room || "default";
  const clients = rooms.get(room);
  if (!clients) return;
  const msg = typeof data === "string" ? data : JSON.stringify(data);
  for (const client of clients) {
    if (client !== ws && client.readyState === 1) {
      client.send(msg);
    }
  }
}

function presence(room) {
  const clients = rooms.get(room);
  return clients ? clients.size : 0;
}

async function registerDisplay(ws, msg) {
  const apiKey = msg.api_key || "";
  const label = String(msg.label || "").slice(0, 80);
  let name = apiKey ? await adaKeyName(apiKey).catch(() => null) : null;

  if (!name) {
    // unpaired display: hold it in a pending slot and show a QR claim code.
    // device_id (persisted in the page's localStorage) re-attaches a
    // reconnecting display to its existing pending slot instead of stacking
    // duplicate "waiting" rows on every drop/reload.
    const devId = String(msg.device_id || "").slice(0, 64);
    if (!ws.pendingSid && devId) {
      for (const [sid, p] of pending) {
        if (p.device_id === devId) { ws.pendingSid = sid; break; }
      }
    }
    if (!ws.pendingSid) {
      const sid = `p${Math.random().toString(36).slice(2, 10)}`;
      ws.pendingSid = sid;
      pending.set(sid, { ws, label, ts: Date.now() });
    }
    const p = pending.get(ws.pendingSid);
    p.ws = ws;
    p.label = label;
    p.ts = Date.now();
    if (devId) p.device_id = devId;
    ws.send(
      JSON.stringify({
        type: "pending",
        sid: ws.pendingSid,
        reason: apiKey ? "key rejected" : "no key",
      })
    );
    return;
  }

  const screen = allocScreen(name);
  const entry = registry.screens[screen];
  if (label) entry.label = label;
  entry.last_seen = new Date().toISOString();
  saveRegistry();

  ws.pendingSid && pending.delete(ws.pendingSid);
  ws.pendingSid = null;
  ws.screen = screen;
  live.set(screen, ws);
  joinRoom(ws, `vcast-${screen}`);
  ws.send(JSON.stringify({ type: "registered", screen, name }));
  // restore the last casts after a reconnect — pane-keyed, layout first so
  // content lands in the right sub-screens (a ws flap no longer blanks it)
  const prefix = `vcast-${screen}|`;
  const replay = [...lastCast.entries()]
    .filter(([k]) => k.startsWith(prefix))
    // layout messages carry no pane — send them first so content lands
    // in the right sub-screens
    .sort(([, a], [, b]) =>
      (a.type === "layout" ? 0 : 1) - (b.type === "layout" ? 0 : 1));
  for (const [, msg] of replay)
    setTimeout(() => { try { ws.send(JSON.stringify(msg)); } catch (e) {} }, 400);
}

const wss = new WebSocketServer({ noServer: true });

wss.on("connection", (ws) => {
  joinRoom(ws, "default");

  ws.on("message", (raw) => {
    let msg;
    try {
      msg = JSON.parse(raw.toString("utf8"));
    } catch (e) {
      return;
    }

    if (msg && msg.type === "join") {
      const room = msg.room || "default";
      joinRoom(ws, room);
      ws.send(JSON.stringify({ type: "presence", room, count: presence(room) }));
      return;
    }

    if (msg && msg.type === "register-display") {
      registerDisplay(ws, msg).catch((e) =>
        console.error("[vcast] register failed:", e.message)
      );
      return;
    }

    // state reports from a registered screen update the registry
    if (msg && msg.type === "state" && ws.screen != null) {
      const entry = registry.screens[ws.screen];
      if (entry) {
        entry.state = String(msg.state || "idle").slice(0, 32);
        entry.state_detail = String(msg.detail || "").slice(0, 200);
        // pane count for split screens — "layout" state carries
        // "N pane(s)" in detail; idle resets to 1 so a pane-targeted
        // cast can tell whether it fills a sub-screen or the whole thing
        if (entry.state === "layout") {
          const m = entry.state_detail.match(/^(\d+)/);
          if (m) entry.panes = parseInt(m[1], 10);
        } else if (entry.state === "idle") {
          entry.panes = 1;
        }
        entry.last_seen = new Date().toISOString();
        saveRegistry();
      }
      broadcastTo("vcast-ctl", { ...msg, screen: ws.screen });
      return;
    }

    broadcast(ws, msg);
  });

  ws.on("close", () => {
    releaseScreenByWs(ws);
    leaveRoom(ws);
    if (ws.pendingSid) pending.delete(ws.pendingSid);
    for (const [sid, p] of pending) if (p.ws === ws) pending.delete(sid);
  });
  ws.on("error", (e) => console.error("[input-bridge] client error", e.message));
});

server.on("upgrade", (req, socket, head) => {
  const pathname = new URL(req.url, "http://x").pathname;
  if (["/pub", "/displays", "/claim", "/health", "/pair-info", "/frame", "/camwall"].includes(pathname)) {
    socket.destroy();
    return;
  }
  wss.handleUpgrade(req, socket, head, (ws) => wss.emit("connection", ws, req));
});

loadRegistry();
server.listen(PORT, BIND, () => {
  console.log(`[input-bridge] http+ws listening on ${BIND}:${PORT}`);
  console.log(`[input-bridge] rooms: default; join via {type:"join", room:"..."}`);
  console.log(`[input-bridge] vcast: GET /displays POST /pub POST /claim GET /pair-info`);
  console.log(`[input-bridge] registry: ${REGISTRY_FILE}`);
  console.log(`[input-bridge] ada auth: ${ADA_AUTH_URL || "(disabled)"}`);
});

setInterval(() => {
  for (const [, clients] of rooms) {
    for (const ws of clients) {
      if (ws.readyState === 1) {
        ws.send(JSON.stringify({ type: "ping" }));
      }
    }
  }
  pendingCleanup();
  // prune display registrations untouched for 72h — stale test devices
  // otherwise pile up in /displays forever (iPad sleeping overnight is safe:
  // it re-registers and re-renders via lastCast replay)
  const cutoff = Date.now() - 72 * 3600e3;
  let pruned = false;
  for (const [n, s] of Object.entries(registry.screens)) {
    if (live.has(Number(n))) continue;
    const seen = Date.parse(s.last_seen || s.assigned_at || 0);
    if (seen && seen < cutoff) {
      console.log(`[vcast] pruning stale screen ${n} (${s.name || s.label})`);
      delete registry.screens[n];
      pruned = true;
    }
  }
  if (pruned) saveRegistry();
}, PING_INTERVAL_MS);
