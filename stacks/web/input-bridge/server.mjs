#!/usr/bin/env node
"use strict";

import http from "node:http";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { WebSocketServer } from "ws";

const PORT = parseInt(process.env.INPUT_BRIDGE_PORT || "3010", 10);
const PING_INTERVAL_MS = 30000;
const PENDING_TTL_MS = parseInt(process.env.VCAST_PENDING_TTL_MS || "300000", 10);
const ADA_AUTH_URL = (process.env.ADA_AUTH_URL || "").replace(/\/+$/, "");
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

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = "";
    req.on("data", (c) => {
      data += c;
      if (data.length > 65536) {
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
    const { sid, admin_key, force } = body;
    if (!sid || !pending.has(sid)) {
      return json(res, 404, { error: "unknown or expired sid" });
    }
    if (!admin_key) return json(res, 400, { error: "admin_key required" });
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

    const screen = allocScreen(name);
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
    const { admin_key } = body;
    if (!admin_key) return json(res, 400, { error: "admin_key required" });
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
      const ws = live.get(parseInt(entry[0], 10));
      if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: "unpaired" }));
      delete registry.screens[entry[0]];
      saveRegistry();
    }
    return json(res, 200, { ok: true, name, revoked });
  }

  json(res, 404, { error: "not found" });
});

// ---------------------------------------------------------------------------
// WebSocket relay
// ---------------------------------------------------------------------------
const rooms = new Map();

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
    // unpaired display: hold it in a pending slot and show a QR claim code
    if (!ws.pendingSid) {
      const sid = `p${Math.random().toString(36).slice(2, 10)}`;
      ws.pendingSid = sid;
      pending.set(sid, { ws, label, ts: Date.now() });
    }
    pending.get(ws.pendingSid).label = label;
    pending.get(ws.pendingSid).ts = Date.now();
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
  if (["/pub", "/displays", "/claim", "/health", "/pair-info"].includes(pathname)) {
    socket.destroy();
    return;
  }
  wss.handleUpgrade(req, socket, head, (ws) => wss.emit("connection", ws, req));
});

loadRegistry();
server.listen(PORT, () => {
  console.log(`[input-bridge] http+ws listening on 0.0.0.0:${PORT}`);
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
}, PING_INTERVAL_MS);
