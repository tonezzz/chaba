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
// Rebind grace: a disconnected display's registry entry holds its name+slot
// for this long so a ws flap rebinds in place; past it the name frees and
// the entry is swept (the 2026-10-09 dead-entry pileup: every stale socket
// left a screen-N entry that pinned the name forever — vcast-real-6
// accumulated slots 1,6,8,9 while drifting onto lowest-free).
const GRACE_MS = parseInt(process.env.VCAST_GRACE_MS || "60000", 10);
// /release tombstones live this long — bounded purely so the registry file
// can't grow without limit on churned names.
const TOMBSTONE_TTL_MS = parseInt(process.env.VCAST_TOMBSTONE_TTL_MS
  || String(30 * 24 * 3600e3), 10);
// sweep cadence — tests shrink this alongside GRACE_MS
const SWEEP_MS = parseInt(process.env.VCAST_SWEEP_MS
  || String(PING_INTERVAL_MS), 10);
// App-level silence: displays heartbeat a state report every 30s, so a
// live socket with no report past this is treated stale — a frozen
// display (iOS suspend, dead headless chromium) still answers protocol
// pings while its app is gone; last_seen is the only honest clock.
// (2026-10-22 live example: screens 2/4 read connected:true with a
// 6-day-old last_seen.)
const STALE_SEEN_MS = parseInt(process.env.VCAST_STALE_SEEN_MS || "120000", 10);
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
const registry = { screens: {}, tombstones: {}, codes: {} };
const live = new Map(); // screen number -> ws
const pending = new Map(); // sid -> {ws, label, ts, code}
const sockets = new Set(); // every ws the server accepted (for ping sweeps)

// Audit timeline — claim/release/resurrect/register/disconnect/sweep
// events, persisted next to the registry so a restart doesn't lose the
// forensic trail (the 2026-10-09 flap post-mortem had only journald).
// Surfaced in /displays (recent tail) so the operator view can render
// it, and counted for the 24h flap metric.
const EVENTS_FILE =
  process.env.VCAST_EVENTS ||
  path.join(path.dirname(REGISTRY_FILE), "displays-events.json");
const EVENTS_CAP = 400;
const events = []; // {at, kind, ...}
function loadEvents() {
  try {
    const data = JSON.parse(fs.readFileSync(EVENTS_FILE, "utf8"));
    if (Array.isArray(data)) events.push(...data.slice(-EVENTS_CAP));
  } catch (e) { /* fresh log */ }
}
function saveEvents() {
  try {
    fs.mkdirSync(path.dirname(EVENTS_FILE), { recursive: true });
    fs.writeFileSync(EVENTS_FILE, JSON.stringify(events, null, 2));
  } catch (e) {
    console.error("[input-bridge] events save failed:", e.message);
  }
}
function logEvent(kind, detail = {}) {
  events.push({ at: new Date().toISOString(), kind, ...detail });
  if (events.length > EVENTS_CAP)
    events.splice(0, events.length - EVENTS_CAP);
  saveEvents();
}
loadEvents();

// Flap = an abnormal display disconnect (close code other than the benign
// client-lifecycle ones) or a supersede (re-register over a live socket).
// Same definition vcast-auto-health.py applies to journald — keep in sync.
const BENIGN_CLOSE_CODES = new Set([1000, 1001, 1005]);
function flapStats() {
  const dayAgo = Date.now() - 24 * 3600e3;
  let flaps_24h = 0, last_flap = null;
  for (const e of events) {
    if (e.kind !== "supersede" &&
        !(e.kind === "disconnect" && e.abnormal)) continue;
    if (Date.parse(e.at) < dayAgo) continue;
    flaps_24h++;
    if (!last_flap || e.at > last_flap) last_flap = e.at;
  }
  return { flaps_24h, last_flap };
}

// Spoken claim codes: a pending display shows a 4-digit code under its QR
// so a bystander can tell Ada "claim code 4821" instead of scanning —
// voice-first pairing. Unique among pending entries AND live screens —
// registered screens keep a persistent code (minted once at register,
// stored in the registry) as their durable "take control" voice id.
function mintClaimCode() {
  for (;;) {
    const c = String(1000 + Math.floor(Math.random() * 9000));
    if ([...pending.values()].some(p => p.code === c)) continue;
    if (Object.values(registry.screens).some(s => s.code === c)) continue;
    if (Object.values(registry.codes).includes(c)) continue;
    return c;
  }
}
function sidForCode(code) {
  const c = String(code || "").trim();
  if (!/^\d{4}$/.test(c)) return "";
  for (const [sid, p] of pending) if (p.code === c) return sid;
  return "";
}

function loadRegistry() {
  try {
    const data = JSON.parse(fs.readFileSync(REGISTRY_FILE, "utf8"));
    if (data && typeof data.screens === "object") registry.screens = data.screens;
    if (data && typeof data.tombstones === "object")
      registry.tombstones = data.tombstones;
    if (data && typeof data.codes === "object") registry.codes = data.codes;
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

function slotLive(n) {
  const w = live.get(n);
  return !!(w && w.readyState === 1);
}

// Dead entries hold their name+slot for the rebind grace; past it the slot
// is fair game (the sweep deletes the entry outright).
function deadStamp(s) {
  return Date.parse(s.disconnected_at || s.last_seen || s.assigned_at || 0);
}
function reclaimable(n) {
  const s = registry.screens[n];
  if (!s || slotLive(n)) return false;
  const t = deadStamp(s);
  return !t || Date.now() - t > GRACE_MS;   // unknown age = stale
}
function usedSlots() {
  const used = new Set();
  for (const [n] of Object.entries(registry.screens)) {
    const num = parseInt(n, 10);
    if (!reclaimable(num)) used.add(num);
  }
  return used;
}

function allocScreen(name) {
  // screen-N names pin their slot: a display re-registering with a
  // persisted key takes slot N when free, and a drifted binding (name on
  // the wrong slot) migrates home — only /claim honored N before, so a
  // relay restart with a fresh registry scrambled every number
  // (2026-10-06: screen-6 landed on slot 1, screen-1 on slot 4).
  const wanted = parseInt((name.match(/^screen-(\d+)$/) || [])[1] || "0", 10);
  for (const [n, s] of Object.entries(registry.screens)) {
    if (s.name !== name) continue;
    const cur = parseInt(n, 10);
    delete s.disconnected_at;              // rebind clears the grace stamp
    if (wanted && wanted !== cur && !registry.screens[wanted]) {
      registry.screens[wanted] = s;
      delete registry.screens[cur];
      const ws = live.get(cur);
      if (ws) {           // keep the live binding on the moved slot
        live.delete(cur);
        live.set(wanted, ws);
        ws.screen = wanted;
      }
      saveRegistry();
      return wanted;
    }
    return cur;
  }
  // reclaimable (dead past grace) slots don't block allocation — the sweep
  // is about to delete them anyway
  const used = usedSlots();
  let n = wanted && !used.has(wanted) ? wanted : 1;
  while (used.has(n)) n++;
  registry.screens[n] = { name, assigned_at: new Date().toISOString() };
  saveRegistry();
  return n;
}

function releaseScreenByWs(ws) {
  if (ws.screen == null) return;
  // only the CURRENT live socket may release the slot — a stale socket
  // that kept ws.screen must not evict a display that re-registered
  if (live.get(ws.screen) === ws) {
    live.delete(ws.screen);
    // keep the entry for the rebind grace — stamp it so the sweep frees
    // the name+slot once the window lapses without a re-register
    const s = registry.screens[ws.screen];
    if (s) {
      s.disconnected_at = new Date().toISOString();
      saveRegistry();
    }
    console.log(`[vcast] screen ${ws.screen} disconnected`);
  }
  ws.screen = null;
}

function pendingCleanup() {
  const now = Date.now();
  for (const [sid, p] of pending) {
    if (now - p.ts > PENDING_TTL_MS || !p.ws || p.ws.readyState !== 1) {
      logEvent("pending-expire", { sid, label: p.label || null });
      pending.delete(sid);
    }
  }
}

// ---------------------------------------------------------------------------
// Lifecycle — the operator-facing truth per screen (vcast-ux-flow). One
// derived state, never "registered-but-dead": pairing (pending row or a
// claim awaiting its register), connected (live socket, no state report
// yet), idle, playing (any content state), reconnecting (socket dead but
// inside the rebind grace — the name is still held), stale (dead past
// grace, awaiting the sweep), released (tombstoned name).
// ---------------------------------------------------------------------------
function lifecycleOf(num, s) {
  const now = Date.now();
  if (slotLive(num)) {
    // socket open but app silent — the zombie case: reads "stale", not
    // "connected", because registry presence (or even a live socket)
    // isn't proof the display works
    const seen = Date.parse(s.last_seen || 0);
    if (seen && now - seen > STALE_SEEN_MS) {
      return { state: "stale", age_s: Math.round((now - seen) / 1000),
               silent_socket: true };
    }
    const st = s.state || "";
    if (!st) return { state: "connected" };
    if (st === "idle") return { state: "idle" };
    return { state: "playing", detail: st };
  }
  // claim in flight — /claim minted the key, register hasn't landed.
  // Checked before the dead-stamp path: /claim re-proofs disconnected_at
  // to restart the rebind window, so an in-flight claim would otherwise
  // read "reconnecting" when it's really "pairing".
  if (s.claimed_at) {
    return { state: "pairing",
             age_s: Math.round((now - Date.parse(s.claimed_at)) / 1000) };
  }
  const dead = deadStamp(s);
  const age_s = dead ? Math.round((now - dead) / 1000) : null;
  if (dead && now - dead < GRACE_MS) {
    return { state: "reconnecting", age_s,
             reclaim_in_s: Math.ceil((GRACE_MS - (now - dead)) / 1000) };
  }
  // past grace (or no stamp — treated stale) — the sweep is owed
  return { state: "stale", age_s };
}

function lastCastFor(num) {
  // per-pane view of what the display would replay on reconnect — the
  // honest "what should be on this screen" answer
  const out = [];
  for (const [k, v] of lastCast) {
    if (!k.startsWith(`vcast-${num}|`)) continue;
    const m = v.msg || v;              // tolerate pre-wrap entries
    out.push({
      pane: k.slice(`vcast-${num}|`.length) || "0",
      type: m.type || "?",
      url: m.url ? String(m.url).slice(0, 160) : null,
      at: v.at ? new Date(v.at).toISOString() : null,
      panes: m.panes ?? m.layout ?? null,
    });
  }
  return out;
}

// A name is held while a live display owns it or a rival /claim already
// minted a key that hasn't registered yet (claimed_at marks the
// claim->register gap). A dead entry past the rebind grace is NOT held —
// it frees on the next sweep anyway.
function nameHeld(name) {
  const ent = Object.entries(registry.screens)
    .find(([, s]) => s.name === name);
  if (!ent) return false;
  const num = parseInt(ent[0], 10);
  return slotLive(num) || (!!ent[1].claimed_at && !reclaimable(num));
}

// /claim serialization: name resolution -> ada mint/resurrect -> redeem ->
// slot alloc -> pair is one atomic unit. Two clients racing the same
// tombstoned name can't both resurrect+pair — the loser runs after the
// winner commits and sees the name held (409 for an explicit name, next
// free slot for want_screen). Claims are rare and ada hops are ~ms, so a
// single tail is enough.
let claimTail = Promise.resolve();
function withClaimLock(fn) {
  const p = claimTail.then(() => fn());
  claimTail = p.catch(() => {});
  return p;
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

async function adaResurrectScreenKey(adminKey, name) {
  // Revoked/released screen names keep their ada key (DELETE = revoke,
  // the name stays taken) so a plain keys POST 409s. Resurrection runs
  // the member-invite chain instead of revoke+re-mint — the existing key
  // is re-approved, never destroyed, so a display still holding it is
  // unaffected. The invite+approve steps are best-effort (they 409/404
  // when the name is already approved or an invite exists); the mint is
  // authoritative — it only returns a redeem_url for an approved key.
  await adaFetch("/api/auth/invites", {
    method: "POST",
    headers: { "content-type": "application/json", "x-api-key": adminKey },
    body: JSON.stringify({ name }),
  });
  await adaFetch(`/api/auth/keys/${encodeURIComponent(name)}/approve`, {
    method: "POST",
    headers: { "x-api-key": adminKey },
  });
  const mint = await adaFetch(`/api/auth/invites/${encodeURIComponent(name)}`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-api-key": adminKey },
    body: JSON.stringify({ path: "/", redirect: "/apps/vcast" }),
  });
  if (mint && mint.status === 409) return { conflict: true };
  if (!mint || !mint.ok)
    return { error: `ada invite mint -> ${mint ? mint.status : "unreachable"}` };
  return await mint.json().catch(() => ({ error: "bad ada invite response" }));
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
  const now = Date.now();
  const labelUse = {};
  for (const s of Object.values(registry.screens)) {
    const l = s.label || s.name;
    labelUse[l] = (labelUse[l] || 0) + 1;
  }
  const screens = Object.entries(registry.screens).map(([n, s]) => {
    const num = parseInt(n, 10);
    const ws = live.get(num);
    const lc = lifecycleOf(num, s);
    const wanted = parseInt(
      (String(s.name).match(/^screen-(\d+)$/) || [])[1] || "0", 10);
    return {
      screen: num,
      name: s.name,
      label: s.label || s.name,
      // identity: screen-N names pin slot N — flag drift so the UI can
      // show preferred vs assigned instead of a bare number
      preferred_screen: wanted || null,
      drift: !!(wanted && wanted !== num),
      label_dup: labelUse[s.label || s.name] > 1,
      assigned_at: s.assigned_at,
      connected: !!(ws && ws.readyState === 1),
      lifecycle: lc.state,
      lifecycle_detail: lc.detail || null,
      silent_socket: lc.silent_socket || undefined,
      age_s: lc.age_s ?? null,
      reclaim_in_s: lc.reclaim_in_s ?? null,
      disconnected_at: s.disconnected_at || null,
      last_seen: s.last_seen || null,
      state: s.state || "idle",
      state_detail: s.state_detail || null,
      panes: s.panes || 1,
      code: s.code || null,
      last_cast: lastCastFor(num),
    };
  });
  screens.sort((a, b) => a.screen - b.screen);
  const health = {
    connected: 0, reconnecting: 0, stale: 0,
    pending: pending.size, released: 0,
    grace_ms: GRACE_MS,
    ...flapStats(),
  };
  for (const s of screens) {
    if (s.lifecycle === "idle" || s.lifecycle === "playing" ||
        s.lifecycle === "connected") health.connected++;
    else if (s.lifecycle === "reconnecting") health.reconnecting++;
    else if (s.lifecycle === "stale") health.stale++;
  }
  const released = Object.entries(registry.tombstones)
    .map(([name, at]) => ({
      name, at,
      reclaim_until: new Date(Date.parse(at) + TOMBSTONE_TTL_MS)
        .toISOString(),
      age_s: Math.round((now - Date.parse(at)) / 1000),
    }))
    .sort((a, b) => b.at.localeCompare(a.at));
  health.released = released.length;
  return {
    screens,
    pending: [...pending.entries()].map(([sid, p]) => ({
      sid,
      label: p.label || null,
      code: p.code || null,
      device_id: p.device_id ? String(p.device_id).slice(0, 8) : null,
      since: new Date(p.ts).toISOString(),
      expires_in_s: Math.max(0,
        Math.ceil((PENDING_TTL_MS - (now - p.ts)) / 1000)),
    })),
    released,
    health,
    events: events.slice(-40).reverse(),
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
      tombstones: Object.keys(registry.tombstones).length,
      ada_auth: !!ADA_AUTH_URL,
      events: events.length,
      ...flapStats(),
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

  // Percussion music control: GET reads the active control, POST sets
  // style/mood/instruments — Ada's percussion_set tool uses this.
  if (req.method === "GET" && url.pathname === "/percussion") {
    return json(res, 200, {
      control: percControl,
      choices: {
        styles: [...PERC_STYLE], moods: [...PERC_MOOD],
        instruments: [...PERC_INS],
      },
    });
  }

  if (req.method === "POST" && url.pathname === "/percussion") {
    let body;
    try {
      body = await readBody(req);
    } catch (e) {
      return json(res, 400, { error: e.message });
    }
    if ("style" in body)
      percControl.style = PERC_STYLE.has(body.style) ? body.style : "";
    if ("mood" in body)
      percControl.mood = PERC_MOOD.has(body.mood) ? body.mood : "";
    if (Array.isArray(body.instruments))
      percControl.instruments = body.instruments.filter(i => PERC_INS.has(i));
    savePercControl();
    return json(res, 200, { ok: true, control: percControl });
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
    if (!p) return json(res, 404, {
      error: "unknown or expired sid",
      next: "the pairing window lapsed — the display re-shows a fresh QR within seconds; rescan it",
    });
    return json(res, 200, {
      sid,
      label: p.label || null,
      code: p.code || null,
      since: new Date(p.ts).toISOString(),
      expires_in_s: Math.max(0,
        Math.ceil((PENDING_TTL_MS - (Date.now() - p.ts)) / 1000)),
    });
  }

  // GET /claim-resolve?code=NNNN — resolve a 4-digit code to its target:
  // pending display -> {sid} for the /claim path; registered screen ->
  // {screen} so voice/tools can say "control display 4821" -> screen N.
  if (req.method === "GET" && url.pathname === "/claim-resolve") {
    const code = String(url.searchParams.get("code") || "").trim();
    const sid = sidForCode(code);
    if (sid) return json(res, 200, { ok: true, kind: "pending", sid });
    for (const [n, s] of Object.entries(registry.screens)) {
      if (s.code && String(s.code) === code) {
        return json(res, 200, { ok: true, kind: "screen",
          screen: parseInt(n, 10), label: s.label || s.name });
      }
    }
    return json(res, 404, { error: "unknown code" });
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
    const meta = url.searchParams.get("meta") === "1";
    const hit = lastFrames.has(`${screen}:${token || ""}`)
        ? [`${screen}:${token || ""}`, lastFrames.get(`${screen}:${token || ""}`)]
        : (token ? null : [...lastFrames.entries()]
             .filter(([k]) => k.startsWith(`${screen}:`))
             .sort((a, b) => b[1].ts - a[1].ts)[0]);
    const f = hit?.[1];
    if (!f) {
      return json(res, 404, {
        error: "frame not ready", screen,
        state: f ? f.state : null,
      });
    }
    // meta=1: JSON envelope instead of the raw body — lets consumers read
    // which token the newest frame arrived under (gesture-N -> screen N)
    if (meta) {
      return json(res, 200, {
        ok: true, screen, key: hit[0], ts: f.ts, state: f.state,
        error: f.error || null,
        data: f.buf ? "data:image/jpeg;base64," + f.buf.toString("base64") : null,
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
    const sid = body.sid || sidForCode(body.code);
    if (!sid || !pending.has(sid)) {
      return json(res, 404, { error: "unknown or expired sid/code" });
    }
    if (!body.admin_key && !tailnetClient(req)) {
      return json(res, 403, { error: "admin key required off-tailnet" });
    }
    const admin_key = body.admin_key || ADA_ADMIN_KEY;
    if (!admin_key) return json(res, 403, { error: "no admin key configured" });
    const adminName = await adaKeyName(admin_key).catch(() => null);
    if (!adminName) return json(res, 403, { error: "admin key not accepted" });

    // body.force is accepted-but-ignored: a name conflict no longer
    // revoke+re-mints (that killed live displays' keys) — resurrection
    // via the ada invite chain is automatic once per claim.
    const explicitName = !!String(body.name || "").trim();
    return withClaimLock(async () => {
      // re-check inside the lock — a queued claim's display may have
      // been claimed/dismissed while a rival claim held the tail
      if (!pending.has(sid))
        return json(res, 404, { error: "unknown or expired sid" });

      let name = String(body.name || "").trim();
      let wanted = parseInt(
        (name.match(/^screen-(\d+)$/) || [])[1] || "0", 10);
      // alternates: {want_screen: N} or {screen: N} — same honoring rule
      const altWant = parseInt(body.want_screen ?? body.screen ?? "0", 10);
      if (!wanted && altWant > 0) {
        wanted = altWant;
        if (!name) name = `screen-${wanted}`;
      }
      if (!name || wanted) {
        // allocate: reuse the requested number when free, else lowest free.
        // A DEAD holder does not keep the slot — the 2026-10-09 drift bug:
        // every reclaim of screen-6 while its stale entry lingered got
        // renamed to lowest-free (screen-8/9/10), stacking dead entries.
        const used = usedSlots();
        let n = wanted;
        if (n && used.has(n)) {
          const occ = registry.screens[n];
          if (occ.name !== name && slotLive(n)) {
            n = 0;                       // a different LIVE display owns it
          } else if (occ.name !== name) {
            // dead holder with a different name — reclaim the slot
            console.log(`[vcast] claim evicts dead ${occ.name} from slot ${n}`);
            const deadWs = live.get(n);
            if (deadWs) { deadWs.screen = null; live.delete(n); leaveRoom(deadWs); }
            delete registry.screens[n];
            used.delete(n);
          }
          // same-name dead entry: keep n — allocScreen() rebinds in place
        }
        if (!n) {
          n = 1;
          while (used.has(n)) n++;
        }
        name = `screen-${n}`;
      }

      // A held name is untouchable: resurrecting/minting it would pair a
      // second display that supersedes the live one on register (the
      // force-loop re-tombstone bug — a retry loop on a live name killed
      // its key). Explicit-name claims conflict; number-derived claims
      // take the next free slot.
      if (nameHeld(name)) {
        const held = Object.entries(registry.screens)
          .find(([, s]) => s.name === name);
        const heldNum = held ? parseInt(held[0], 10) : 0;
        const live_held = heldNum ? slotLive(heldNum) : false;
        const dead = held ? deadStamp(held[1]) : 0;
        const retryIn = dead
          ? Math.max(0, Math.ceil((GRACE_MS - (Date.now() - dead)) / 1000))
          : 0;
        if (explicitName) {
          // reason AND next action — the operator should never have to
          // read journald to learn why a claim refused
          return json(res, 409, {
            error: `name ${name} is in use`, name,
            held_by: live_held ? "live socket" : "claim in flight",
            retry_in_s: live_held ? null : retryIn || null,
            next: live_held
              ? `release the live display first (POST /release {screen:${heldNum}}) or pick another name`
              : `name held by a dead socket — retry in ~${retryIn}s or POST /sweep {screen:${heldNum}}`,
          });
        }
        const used = usedSlots();
        let n = 1;
        while (used.has(n)) n++;
        name = `screen-${n}`;
        wanted = n;
      }

      let created = await adaCreateScreenKey(admin_key, name);
      let resurrected = false;
      if (created.conflict && /^screen-\d+$/.test(name)) {
        // released/stale screen-N names keep their ada key — resurrect
        // once via the invite chain. Non-screen names are member keys:
        // they keep tombstone semantics and stay a hard 409.
        created = await adaResurrectScreenKey(admin_key, name);
        resurrected = true;
      }
      if (created.conflict) {
        return json(res, 409, {
          error: `name ${name} already issued`, name,
          held_by: "ada key",
          next: "non-screen names keep tombstone semantics — pick another name or manage the key in ada",
        });
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
      // re-proof a rebound dead entry: restart the rebind window from the
      // claim — the minted key's register lands well inside it, and a
      // claim that never attaches is swept like any dead entry
      registry.screens[screen].disconnected_at = new Date().toISOString();
      // claim-in-flight marker: rival claims for this name see it held
      // until the minted key registers (cleared in registerDisplay)
      registry.screens[screen].claimed_at = new Date().toISOString();
      // a successful (re-)mint lifts the tombstone — /release only bars
      // the name until someone deliberately claims it again
      const reclaimed = !!registry.tombstones[name];
      delete registry.tombstones[name];
      saveRegistry();
      logEvent("claim", {
        name, screen, sid,
        resurrected: resurrected || undefined,
        reclaimed: reclaimed || undefined,
      });

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
      return json(res, 200, { ok: true, screen, name, resurrected });
    // ada hops abort on timeout — a throw must answer, not hang
    }).catch((e) => json(res, 502, { error: `claim failed: ${e.message}` }));
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
    if (!name) return json(res, 404, {
      error: "unknown screen",
      next: "the screen may already be released or swept — check GET /displays for the live registry",
    });

    const revoked = await adaRevokeKey(admin_key, name);
    // Tombstone the released name: the detached socket's late state writes
    // are already gated by live[], but a still-valid key (revoke lagging
    // or failed) let a zombie re-register and RE-CREATE the entry — the
    // 2026-10-09 resurrection. The tombstone blocks registerDisplay until
    // a fresh /claim re-mints the name.
    const tombstonedAt = new Date().toISOString();
    registry.tombstones[name] = tombstonedAt;
    let releasedScreen = null;
    const entry = Object.entries(registry.screens).find(([, s]) => s.name === name);
    if (entry) {
      const num = parseInt(entry[0], 10);
      releasedScreen = num;
      const ws = live.get(num);
      if (ws) {
        if (ws.readyState === 1)
          ws.send(JSON.stringify({ type: "unpaired", reason: "released" }));
        // detach now — the stale socket's later close would otherwise
        // evict a re-registered display from live[]
        ws.screen = null;
        live.delete(num);
        // close politely after the unpaired frame — keeps the zombie
        // from lingering in the room while its page settles on the QR
        try { ws.close(1000, "released"); } catch (e) {}
      }
      // stale casts for the released room must not replay onto the next
      // display to claim this slot
      for (const k of [...lastCast.keys()])
        if (k.startsWith(`vcast-${num}|`)) lastCast.delete(k);
      delete registry.screens[entry[0]];
    }
    saveRegistry();
    const tombstone_until =
      new Date(Date.parse(tombstonedAt) + TOMBSTONE_TTL_MS).toISOString();
    logEvent("release", { name, screen: releasedScreen, revoked });
    return json(res, 200, {
      ok: true, name, screen: releasedScreen, revoked, tombstone_until,
      note: `released — name reserved ${Math.round(TOMBSTONE_TTL_MS / 86400e3)}d for reclaim (claim a display as ${name} to reuse it)`,
    });
  }

  if (req.method === "POST" && url.pathname === "/sweep") {
    // Force-free a dead/stale registry entry NOW — the one-click fix for
    // "name held by a dead socket". Equivalent to waiting out the rebind
    // grace, but the operator shouldn't have to. Live screens refuse:
    // sweeping a connected display would orphan it mid-cast — release
    // is the honest op for that.
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

    const targets = [];
    if (body.all === true || body.stale === true) {
      for (const [n, s] of Object.entries(registry.screens)) {
        const num = parseInt(n, 10);
        if (!slotLive(num)) targets.push([num, s]);
      }
    } else {
      const num = parseInt(body.screen, 10);
      const s = registry.screens[num];
      if (!Number.isInteger(num) || !s) {
        return json(res, 404, {
          error: "unknown screen",
          next: "nothing to sweep — the entry is already gone (check GET /displays)",
        });
      }
      if (slotLive(num)) {
        return json(res, 409, {
          error: `screen ${num} is connected — sweeping a live display would orphan it`,
          held_by: "live socket",
          next: `release it instead (POST /release {screen:${num}}) — release tombstones the name; sweep only frees dead entries`,
        });
      }
      targets.push([num, s]);
    }
    const freed = [];
    for (const [num, s] of targets) {
      const ws = live.get(num);
      if (ws) { ws.screen = null; live.delete(num); leaveRoom(ws); }
      for (const k of [...lastCast.keys()])
        if (k.startsWith(`vcast-${num}|`)) lastCast.delete(k);
      delete registry.screens[num];
      freed.push({ screen: num, name: s.name });
      logEvent("sweep", { screen: num, name: s.name, reason: "operator" });
    }
    if (freed.length) saveRegistry();
    return json(res, 200, { ok: true, freed });
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
    if (!p) return json(res, 404, {
      error: "unknown or expired sid",
      next: "the pairing window already lapsed — nothing to dismiss",
    });
    pending.delete(body.sid);
    logEvent("dismiss", { sid: body.sid, label: p.label || null });
    if (p.ws && p.ws.readyState === 1) {
      p.ws.pendingSid = null;
      p.ws.send(JSON.stringify({ type: "dismissed" }));
    }
    return json(res, 200, { ok: true });
  }

  if (req.method === "POST" && url.pathname === "/screen") {
    // Retitle / renumber a registered display at will:
    //   {screen: N, label: "living-room"}  — human name for Ada/reporting
    //   {screen: N, move_to: M}           — re-slot the number live
    // `label` is the display name; `name` stays the ada key identity
    // (renaming that would orphan the display's key on next register).
    // A live display gets a ws "rescreen" push so its HUD stays honest;
    // casts already recorded for vcast-N migrate to vcast-M with it.
    let body;
    try {
      body = await readBody(req);
    } catch (e) {
      return json(res, 400, { error: e.message });
    }
    if (!body.admin_key && !tailnetClient(req)) {
      return json(res, 403, { error: "admin key required off-tailnet" });
    }
    const n = parseInt(body.screen, 10);
    const entry = registry.screens[n];
    if (!Number.isInteger(n) || !entry)
      return json(res, 404, {
        error: "unknown screen",
        next: "the screen may be released or swept — check GET /displays",
      });
    if (body.label != null) {
      const label = String(body.label).slice(0, 80);
      // two live screens must never wear the same label — the operator
      // can't tell them apart (the 2026-10-08 four-entries-one-display)
      const clash = Object.entries(registry.screens).find(([k, s]) =>
        parseInt(k, 10) !== n && (s.label || s.name) === label &&
        slotLive(parseInt(k, 10)));
      if (clash) {
        return json(res, 409, {
          error: `label "${label}" is already on live screen ${clash[0]}`,
          next: `retitle or release screen ${clash[0]} first — duplicate labels defeat the identity rule`,
        });
      }
      entry.label = label;
      logEvent("relabel", { screen: n, name: entry.name, label });
    }
    let final = n;
    const to = parseInt(body.move_to, 10);
    if (to > 0 && to !== n) {
      if (slotLive(to))
        return json(res, 409, {
          error: `screen ${to} is in use by a live display`,
          held_by: "live socket",
          next: `release screen ${to} first, or move to a different slot`,
        });
      if (registry.screens[to] && !reclaimable(to)) {
        const dead = deadStamp(registry.screens[to]);
        const retryIn = dead ? Math.max(0, Math.ceil(
          (GRACE_MS - (Date.now() - dead)) / 1000)) : 0;
        return json(res, 409, {
          error: `screen ${to} is still in its rebind grace`,
          held_by: "dead socket", retry_in_s: retryIn || null,
          next: `retry in ~${retryIn}s or POST /sweep {screen:${to}} to free it now`,
        });
      }
      if (registry.screens[to]) {
        // dead past grace — same evict rule /claim uses
        const deadWs = live.get(to);
        if (deadWs) { deadWs.screen = null; live.delete(to); leaveRoom(deadWs); }
        delete registry.screens[to];
      }
      registry.screens[to] = entry;
      delete registry.screens[n];
      final = to;
      logEvent("move", { name: entry.name, from: n, to });
      const ws = live.get(n);
      if (ws) {
        live.delete(n);
        live.set(to, ws);
        ws.screen = to;
        joinRoom(ws, `vcast-${to}`);   // leaveRoom happens inside joinRoom
        try {
          ws.send(JSON.stringify({
            type: "rescreen", screen: to,
            name: entry.name, label: entry.label || entry.name,
          }));
        } catch (e) {}
      }
      for (const k of [...lastCast.keys()]) {
        if (k.startsWith(`vcast-${n}|`)) {
          lastCast.set(`vcast-${to}|` + k.slice(`vcast-${n}|`.length),
                       lastCast.get(k));
          lastCast.delete(k);
        }
      }
    }
    saveRegistry();
    return json(res, 200, {
      ok: true, screen: final, name: entry.name,
      label: entry.label || entry.name,
      moved: final !== n, connected: slotLive(final),
    });
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

// Percussion music layer: POST writes the app's control.json (style,
// mood, instruments[]) — the web app polls it on its state cadence.
const PERC_CONTROL_FILE =
  process.env.PERC_CONTROL ||
  path.join(process.env.VCAST_CAMWALL
              ? path.dirname(process.env.VCAST_CAMWALL)
              : path.join(os.homedir(), ".local", "share", "input-bridge"),
            "percussion.json");
const PERC_STYLE = new Set(["rock","ballad","funky","electronic","edm",
                            "hardrock","rockballad","polyphia"]);
const PERC_MOOD = new Set(["blue","bright","tense","calm"]);
const PERC_INS = new Set(["bass","stab","pad","lead","guitar","clap",
                          "ride","tamb","rim"]);
const percControl = { style:"", mood:"", instruments:[] };
function savePercControl() {
  try {
    fs.mkdirSync(path.dirname(PERC_CONTROL_FILE), { recursive: true });
    fs.writeFileSync(PERC_CONTROL_FILE,
                     JSON.stringify({ ...percControl,
                                      updated: new Date().toISOString() },
                                    null, 2) + "\n");
  } catch (e) {
    console.error("[input-bridge] percussion control save failed:", e.message);
  }
}
function loadPercControl() {
  try {
    const c = JSON.parse(fs.readFileSync(PERC_CONTROL_FILE, "utf8"));
    if (PERC_STYLE.has(c.style)) percControl.style = c.style;
    if (PERC_MOOD.has(c.mood)) percControl.mood = c.mood;
    if (Array.isArray(c.instruments))
      percControl.instruments = c.instruments.filter(i => PERC_INS.has(i));
  } catch (e) { /* fresh state */ }
}
loadPercControl();

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
  // remember display-state casts BEFORE the no-clients bail — a cast that
  // lands while a display is mid-reconnect (the room evaporates on the
  // last leave) must still replay on re-register; previously it was
  // dropped and the re-register replayed the STALE earlier cast instead
  const msg = typeof data === "string" ? data : JSON.stringify(data);
  try {
    const obj = typeof data === "string" ? JSON.parse(data) : data;
    if (["play", "image", "nav", "stop", "layout", "zoom"].includes(obj?.type)) {
      const pane = obj.pane ?? "";
      // layout/stop reshape the whole screen — flush older pane state
      if (obj.type === "layout" || (obj.type === "stop" && pane === "")) {
        for (const k of [...lastCast.keys()])
          if (k.startsWith(room + "|")) lastCast.delete(k);
      }
      // wrapped {msg, at} — the displays view shows "cast X to pane P
      // at T" per screen, and the operator can see a stale replay set
      lastCast.set(`${room}|${pane}`, { msg: obj, at: Date.now() });
    }
  } catch (e) { /* ignore */ }
  const clients = rooms.get(room);
  if (!clients) return 0;
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
      pending.set(sid, { ws, label, ts: Date.now(), code: mintClaimCode() });
      logEvent("pending", { sid, label: label || null,
                            reason: apiKey ? "key rejected" : "no key" });
    }
    const p = pending.get(ws.pendingSid);
    p.ws = ws;
    p.label = label;
    p.ts = Date.now();
    if (devId) p.device_id = devId;
    if (!p.code) p.code = mintClaimCode();   // entries predating codes
    ws.send(
      JSON.stringify({
        type: "pending",
        sid: ws.pendingSid,
        code: p.code,
        ttl_ms: PENDING_TTL_MS,
        reason: apiKey ? "key rejected" : "no key",
      })
    );
    return;
  }

  // released names are tombstoned — a stale socket whose key still
  // resolves (revoke lagging/failed) must not resurrect the entry.
  // The client drops the key and returns to the pairing QR; a fresh
  // /claim lifts the tombstone.
  if (registry.tombstones[name]) {
    console.log(`[vcast] register refused: ${name} is released (tombstoned)`);
    logEvent("register-refused", { name, reason: "tombstoned" });
    ws.send(JSON.stringify({ type: "unpaired", reason: "released" }));
    return;
  }

  // before allocScreen: was this name already bound? (rebind vs fresh)
  const prevEntry = Object.entries(registry.screens)
    .find(([, s]) => s.name === name);
  const wasRebind = !!prevEntry;
  let screen = allocScreen(name);
  // a display may ask for a specific slot (want_screen/screen) — honor it
  // when free instead of settling for the name-default pin
  const wantScreen = parseInt(msg.want_screen ?? "0", 10);
  if (wantScreen > 0 && wantScreen !== screen && !registry.screens[wantScreen]) {
    registry.screens[wantScreen] = registry.screens[screen];
    delete registry.screens[screen];
    screen = wantScreen;
  }
  const entry = registry.screens[screen];
  if (label) entry.label = label;
  delete entry.disconnected_at;
  delete entry.claimed_at;   // claim->register gap closed — name is live-held
  // persistent 4-digit "take control" id — keyed by NAME (codes map) not
  // the screen entry, so the grace sweep freeing a dead entry never
  // remints the code: "control display 4821" stays bound to screen-N
  if (!registry.codes[name]) registry.codes[name] = mintClaimCode();
  entry.code = registry.codes[name];
  entry.last_seen = new Date().toISOString();
  saveRegistry();

  ws.pendingSid && pending.delete(ws.pendingSid);
  ws.pendingSid = null;
  // A reconnect supersedes the previous live socket: detach it so its
  // queued state reports can't overwrite the new display's ground truth
  // and its later close can't evict the new registration (observed
  // 2026-09-28: an iPad ws flap left /displays reporting idle while the
  // screen was rendering the cast).
  const prev = live.get(screen);
  if (prev && prev !== ws) {
    // flap telemetry — counted by vcast-auto-health as the 24h flap metric
    console.log(`[vcast] screen ${screen} (${name}) superseded by new socket`);
    logEvent("supersede", { screen, name, remote: prev.remote || null });
    prev.screen = null;
    leaveRoom(prev);
    try { prev.terminate(); } catch (e) {}
  }
  logEvent("register", {
    screen, name, label: entry.label || null,
    rebind: wasRebind || undefined,
    remote: ws.remote || null,
  });
  ws.screen = screen;
  live.set(screen, ws);
  joinRoom(ws, `vcast-${screen}`);
  ws.send(JSON.stringify({ type: "registered", screen, name,
                           label: entry.label || name,
                           code: entry.code || null }));
  // restore the last casts after a reconnect — pane-keyed, layout first so
  // content lands in the right sub-screens (a ws flap no longer blanks it)
  const prefix = `vcast-${screen}|`;
  const replay = [...lastCast.entries()]
    .filter(([k]) => k.startsWith(prefix))
    // layout messages carry no pane — send them first so content lands
    // in the right sub-screens (entries are {msg, at} wraps)
    .sort(([, a], [, b]) =>
      ((a.msg || a).type === "layout" ? 0 : 1) -
      ((b.msg || b).type === "layout" ? 0 : 1));
  for (const [, v] of replay)
    setTimeout(() => {
      try { ws.send(JSON.stringify(v.msg || v)); } catch (e) {}
    }, 400);
}

const wss = new WebSocketServer({ noServer: true });

wss.on("connection", (ws, req) => {
  sockets.add(ws);
  ws.isAlive = true;
  ws.connectedAt = Date.now();
  // real client IP — edge-proxied sockets all arrive from the proxy's
  // address (every display showed remote=tony-dell, which made the
  // 2026-10-12 flap forensics useless); XFF first hop is the true peer
  ws.remote = req ? clientIp(req) : "";
  ws.on("pong", () => { ws.isAlive = true; });
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

    // state reports from the live display socket update the registry —
    // a superseded socket keeps no ground truth (its ws.screen is
    // detached on re-register; the live check is belt-and-braces).
    // NOTE: this path only ever UPDATES an existing entry — never create
    // here, or a zombie socket resurrects a /release'd screen.
    if (msg && msg.type === "state" && ws.screen != null
        && live.get(ws.screen) === ws) {
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

  ws.on("close", (code, reason) => {
    sockets.delete(ws);
    // close-code forensics for the real-6 flap question: 1001 = client
    // going away (page nav/reload — proves the nav path), 1006 = abnormal
    // (no close frame — proxy/network drop), 1000 clean, ping-timeout
    // kills arrive as 1006 with no peer frame.
    const ageS = ws.connectedAt
      ? Math.round((Date.now() - ws.connectedAt) / 1000) : -1;
    console.log(`[vcast] ws closed code=${code} ` +
      `reason="${String(reason || "")}" screen=${ws.screen ?? "-"} ` +
      `remote=${ws.remote} alive=${ageS}s`);
    if (ws.screen != null) {
      const ent = registry.screens[ws.screen];
      logEvent("disconnect", {
        screen: ws.screen,
        name: ent ? ent.name : null,
        code,
        abnormal: !BENIGN_CLOSE_CODES.has(code) || undefined,
        alive_s: ageS >= 0 ? ageS : undefined,
        remote: ws.remote || null,
      });
    }
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
  for (const ws of sockets) {
    if (ws.readyState === 1) {
      ws.send(JSON.stringify({ type: "ping" }));
      // protocol-level liveness: the JSON ping proves the app loop runs,
      // but only a pong proves the PEER is still there — a half-open
      // socket (proxy silently dropped it) otherwise holds its screen
      // registration forever
      if (!ws.isAlive) {
        console.log(`[vcast] ws ping timeout — terminating ` +
          `screen=${ws.screen ?? "-"} remote=${ws.remote}`);
        try { ws.terminate(); } catch (e) {}
        continue;
      }
      ws.isAlive = false;
      try { ws.ping(); } catch (e) {}
    }
  }
  pendingCleanup();
  // grace sweep: a disconnected entry holds its name+slot for GRACE_MS so
  // a flapping display rebinds in place; past the window the name frees —
  // dead entries must not accumulate (the pre-fix behavior pinned screen-N
  // names on dead sockets until the 72h prune)
  let changed = false;
  for (const [n, s] of Object.entries(registry.screens)) {
    if (!reclaimable(parseInt(n, 10))) continue;
    console.log(`[vcast] freeing dead screen ${n} ` +
      `(${s.name || s.label}) — rebind grace expired`);
    logEvent("sweep", { screen: parseInt(n, 10), name: s.name || null,
                        reason: "grace-expired" });
    delete registry.screens[n];
    changed = true;
  }
  for (const [nm, ts] of Object.entries(registry.tombstones)) {
    if (Date.now() - Date.parse(ts) > TOMBSTONE_TTL_MS) {
      delete registry.tombstones[nm];
      changed = true;
    }
  }
  if (changed) saveRegistry();
}, SWEEP_MS);
