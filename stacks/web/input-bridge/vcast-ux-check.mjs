#!/usr/bin/env node
// vcast-ux-check — exercises the vcast-ux-flow acceptance stages against
// the real server.mjs on loopback (stubbed ada auth):
//
//   PAIRING    pending rows carry code + expiry; claim shows "pairing"
//   IDENTITY   label is primary; preferred-vs-assigned drift + dup-label
//              flags surface; /screen refuses a dup label on a live screen
//   LIFECYCLE  connected/idle/playing/reconnecting(age)/stale(age)/
//              released all derive from socket + timestamps, not
//              registry presence alone
//   CASTING    /pub delivered counts are honest; per-pane last_cast with
//              timestamps lands in /displays
//   RECOVERY   /sweep frees a dead entry, 409s a live one with a next
//              action; /release answers with the tombstone note;
//              errors carry reason + next
//   OPERATOR   health block: connected/reconnecting/stale/pending/
//              released counts + flaps_24h + last_flap
//   AUDIT      events timeline records claim/register/disconnect/sweep/
//              release/dismiss
//   BENCH      disconnect->rebound recovery time printed (self-heal
//              target <60s — server-side rebind should be ms)
//
//   node vcast-ux-check.mjs [path/to/server.mjs]
//
"use strict";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { WebSocket } from "ws";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SERVER = process.argv[2] || path.join(HERE, "server.mjs");
const AUTH_PORT = 13995;
const RELAY_PORT = 13014;
const GRACE_MS = 60000;              // long grace: reconnecting stays
                                     // observable; auto-sweep never fires
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const failures = [];
function check(name, cond, detail = "") {
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
  if (!cond) failures.push(name);
}

// --- stub ada auth: admin "adm"; seeded key names; invite-chain mint ------
const keyNames = { adm: "admin", "key-a": "screen-9", "key-b": "screen-8" };
const issued = new Set();
let mintCounter = 0;
const auth = http.createServer(async (req, res) => {
  const u = new URL(req.url, "http://x");
  const readReq = () => new Promise((r) => {
    let b = "";
    req.on("data", (c) => (b += c));
    req.on("end", () => r(JSON.parse(b || "{}")));
  });
  if (u.pathname === "/api/auth/status") {
    const name = keyNames[u.searchParams.get("api_key")] || null;
    res.writeHead(200, { "content-type": "application/json" });
    return res.end(JSON.stringify({ authenticated: !!name, name }));
  }
  if (u.pathname === "/api/auth/keys" && req.method === "POST") {
    const name = (await readReq()).name;
    if (issued.has(name)) {
      res.writeHead(409, { "content-type": "application/json" });
      return res.end(JSON.stringify({ error: "conflict" }));
    }
    issued.add(name);
    const tok = `tok${++mintCounter}`;
    keyNames[`key-${tok}`] = name;
    res.writeHead(200, { "content-type": "application/json" });
    return res.end(JSON.stringify({
      name, redeem_url: `http://127.0.0.1:${AUTH_PORT}/redeem/${tok}`,
    }));
  }
  if (u.pathname.startsWith("/api/auth/keys/") && req.method === "DELETE") {
    res.writeHead(200, { "content-type": "application/json" });
    return res.end(JSON.stringify({ ok: true }));
  }
  if (u.pathname === "/api/auth/invites" && req.method === "POST") {
    res.writeHead(200, { "content-type": "application/json" });
    return res.end(JSON.stringify({ invite_url: "http://x/i/t" }));
  }
  const apM = u.pathname.match(/^\/api\/auth\/keys\/([^/]+)\/approve$/);
  if (apM && req.method === "POST") {
    res.writeHead(200, { "content-type": "application/json" });
    return res.end(JSON.stringify({ ok: true }));
  }
  const invM = u.pathname.match(/^\/api\/auth\/invites\/([^/]+)$/);
  if (invM && req.method === "POST") {
    const name = decodeURIComponent(invM[1]);
    issued.add(name);
    const tok = `tok${++mintCounter}`;
    keyNames[`key-${tok}`] = name;
    res.writeHead(200, { "content-type": "application/json" });
    return res.end(JSON.stringify({
      name, redeem_url: `http://127.0.0.1:${AUTH_PORT}/redeem/${tok}`,
    }));
  }
  if (u.pathname.startsWith("/redeem/")) {
    const tok = u.pathname.split("/").pop();
    res.writeHead(302, { location: `/apps/vcast/?api_key=key-${tok}` });
    return res.end();
  }
  res.writeHead(404, { "content-type": "application/json" });
  res.end("{}");
});
await new Promise((r) => auth.listen(AUTH_PORT, "127.0.0.1", r));

// --- seed registry: one long-dead entry (stale), one fresh tombstone ------
const regFile = `/tmp/vcast-ux-registry-${process.pid}.json`;
const evFile = `/tmp/vcast-ux-events-${process.pid}.json`;
fs.rmSync(regFile, { force: true });
fs.rmSync(evFile, { force: true });
const twoHoursAgo = new Date(Date.now() - 2 * 3600e3).toISOString();
const oneHourAgo = new Date(Date.now() - 3600e3).toISOString();
fs.writeFileSync(regFile, JSON.stringify({
  screens: {
    "4": { name: "screen-4", label: "stale-lab", state: "nav",
           assigned_at: twoHoursAgo, last_seen: twoHoursAgo,
           disconnected_at: twoHoursAgo },
    "5": { name: "screen-5", label: "stale-lab2",
           assigned_at: twoHoursAgo, last_seen: twoHoursAgo,
           disconnected_at: twoHoursAgo },
  },
  tombstones: { "screen-old": oneHourAgo },
  codes: {},
}, null, 2));

const relay = spawn("node", [SERVER], {
  env: {
    ...process.env,
    INPUT_BRIDGE_PORT: String(RELAY_PORT),
    INPUT_BRIDGE_BIND: "127.0.0.1",
    ADA_AUTH_URL: `http://127.0.0.1:${AUTH_PORT}`,
    ADA_ADMIN_KEY: "adm",
    VCAST_REGISTRY: regFile,
    VCAST_EVENTS: evFile,
    VCAST_REDEEM_HOSTS: "127.0.0.1",
    VCAST_GRACE_MS: String(GRACE_MS),
    VCAST_SWEEP_MS: "60000",         // no auto-sweep during the check
  },
  stdio: ["ignore", "pipe", "pipe"],
});
relay.stdout.on("data", (d) => process.stderr.write(`[relay] ${d}`));
relay.stderr.on("data", (d) => process.stderr.write(`[relay] ${d}`));
await sleep(800);

const apiStatus = async (p, opts) => {
  const r = await fetch(`http://127.0.0.1:${RELAY_PORT}${p}`, opts);
  return { status: r.status, data: await r.json().catch(() => ({})) };
};
const post = (p, body) =>
  apiStatus(p, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
const displays = async () => (await apiStatus("/displays")).data;
const screenEntry = async (n) =>
  (await displays()).screens.find((s) => s.screen === n);
const eventsOf = async () => (await displays()).events || [];
const hasEvent = async (kind, pred = () => true) =>
  (await eventsOf()).some((e) => e.kind === kind && pred(e));

function display(deviceId, apiKey = "", label = "ux-check") {
  const ws = new WebSocket(`ws://127.0.0.1:${RELAY_PORT}/ws`);
  const inbox = [];
  ws.on("error", () => {});
  ws.on("message", (raw) => inbox.push(JSON.parse(raw.toString())));
  ws.on("open", () =>
    ws.send(JSON.stringify({
      type: "register-display", api_key: apiKey, label, device_id: deviceId,
    })));
  ws.waitFor = (type, pred = () => true, ms = 5000) => new Promise((res, rej) => {
    const t = setTimeout(() => rej(new Error(`timeout waiting ${type}`)), ms);
    const poll = setInterval(() => {
      const m = inbox.find((m) => m.type === type && pred(m));
      if (m) { clearTimeout(t); clearInterval(poll); res(m); }
    }, 20);
  });
  ws.inbox = inbox;
  return ws;
}

try {
  // === LIFECYCLE: seeded stale + tombstone derive correctly ============
  let d = await displays();
  const s4 = d.screens.find((s) => s.screen === 4);
  check("seeded dead entry derives stale + age",
    !!s4 && s4.lifecycle === "stale" && s4.age_s >= 7000,
    s4 ? `lifecycle=${s4.lifecycle} age_s=${s4.age_s}` : "missing");
  const rel = (d.released || []).find((t) => t.name === "screen-old");
  check("tombstone listed as released with reclaim window",
    !!rel && Date.parse(rel.reclaim_until) > Date.now() + 29 * 86400e3,
    rel ? `until=${rel.reclaim_until}` : "missing");
  check("health counts seeded state",
    d.health && d.health.stale >= 2 && d.health.released >= 1 &&
    d.health.connected === 0,
    d.health ? JSON.stringify(d.health) : "no health");

  // === PAIRING: pending rows carry code + expiry + dedupe ==============
  const wP = display("dev-x", "", "lab-ipad");
  const pend = await wP.waitFor("pending");
  check("pending msg carries code + ttl",
    /^\d{4}$/.test(pend.code) && pend.ttl_ms > 0,
    `code=${pend.code} ttl=${pend.ttl_ms}`);
  d = await displays();
  const prow = d.pending.find((p) => p.sid === pend.sid);
  check("pending row shows expiry + device id",
    !!prow && prow.expires_in_s > 0 && !!prow.device_id,
    prow ? `expires=${prow.expires_in_s} dev=${prow.device_id}` : "missing");
  wP.send(JSON.stringify({
    type: "register-display", api_key: "", label: "lab-ipad",
    device_id: "dev-x",
  }));
  const pend2 = await wP.waitFor("pending",
    (m) => m.sid === pend.sid || true, 3000);
  d = await displays();
  check("re-register dedupes pending by device_id",
    pend2.sid === pend.sid &&
    d.pending.filter((p) => p.device_id === prow.device_id).length === 1,
    `sid2=${pend2.sid} rows=${d.pending.length}`);

  // === RECOVERY: sweep a dead entry, refuse a live one =================
  const sw = await post("/sweep", { screen: 4 });
  check("sweep frees stale entry",
    sw.status === 200 && (sw.data.freed || [])[0]?.name === "screen-4",
    `status=${sw.status} ${JSON.stringify(sw.data.freed || [])}`);
  check("stale entry gone after sweep",
    !(await screenEntry(4)));
  const swAll = await post("/sweep", { all: true });
  check("sweep all frees remaining dead entries",
    swAll.status === 200 &&
      (swAll.data.freed || []).some((f) => f.name === "screen-5"),
    JSON.stringify(swAll.data.freed || []));
  check("sweep events logged",
    await hasEvent("sweep", (e) => e.name === "screen-4") &&
    await hasEvent("sweep", (e) => e.name === "screen-5"));

  // === claim -> pairing lifecycle -> register ==========================
  const cl = await post("/claim", { sid: pend.sid, name: "screen-9" });
  check("claim ok", cl.status === 200 && cl.data.screen === 9,
    `status=${cl.status} screen=${cl.data.screen}`);
  const s9p = await screenEntry(9);
  check("claim-in-flight derives pairing lifecycle",
    !!s9p && s9p.lifecycle === "pairing",
    s9p ? `lifecycle=${s9p.lifecycle}` : "missing");
  const paired = await wP.waitFor("paired");
  wP.send(JSON.stringify({
    type: "register-display", api_key: paired.api_key, label: "lab-ipad",
    device_id: "dev-x" }));
  const reg = await wP.waitFor("registered");
  check("registered on screen 9", reg.screen === 9, `screen=${reg.screen}`);
  let s9 = await screenEntry(9);
  check("registered screen derives connected",
    s9.lifecycle === "connected" || s9.lifecycle === "idle",
    `lifecycle=${s9.lifecycle}`);

  // === CASTING: honest delivery + last_cast per pane ===================
  const pub1 = await post("/pub", { screen: 9,
    msg: { type: "nav", url: "https://x/page" } });
  check("pub reports delivered count", pub1.data.delivered === 1,
    `delivered=${pub1.data.delivered}`);
  const pub0 = await post("/pub", { screen: 42,
    msg: { type: "play", url: "https://x/v.m3u8" } });
  check("pub to absent screen reports NOT delivered",
    pub0.data.delivered === 0, `delivered=${pub0.data.delivered}`);
  wP.send(JSON.stringify({ type: "state", state: "playing", detail: "0:https://x/page" }));
  await sleep(150);
  s9 = await screenEntry(9);
  check("state report derives playing + detail",
    s9.lifecycle === "playing" && s9.lifecycle_detail === "playing",
    `lifecycle=${s9.lifecycle} detail=${s9.lifecycle_detail}`);
  const cast = (s9.last_cast || []).find((c) => c.type === "nav");
  check("last_cast per pane with timestamp",
    !!cast && cast.pane === "0" && !!cast.at &&
      Date.now() - Date.parse(cast.at) < 10000,
    cast ? `pane=${cast.pane} at=${cast.at}` : "missing");

  // === IDENTITY: label primary, drift flag, dup-label guard ============
  await post("/screen", { screen: 9, label: "dup-label" });
  const wB = display("dev-b", "key-b", "dup-label");
  await wB.waitFor("registered");
  d = await displays();
  const dup = d.screens.filter((s) => s.label_dup);
  check("duplicate live labels flagged",
    dup.length === 2 && dup.every((s) => s.label === "dup-label"),
    `dup=${dup.map((s) => s.screen).join(",")}`);
  const labErr = await post("/screen", { screen: 8, label: "dup-label" });
  check("/screen refuses dup label on a live screen",
    labErr.status === 409 && /dup-label/.test(labErr.data.error || "") &&
      !!labErr.data.next,
    `status=${labErr.status} next=${labErr.data.next || "-"}`);
  const labOk = await post("/screen", { screen: 8, label: "lab-b" });
  check("/screen relabel ok when unique", labOk.status === 200,
    `status=${labOk.status}`);
  const s8 = await screenEntry(8);
  check("identity fields: label primary + preferred slot",
    s8.label === "lab-b" && s8.preferred_screen === 8 && !s8.drift,
    `label=${s8.label} preferred=${s8.preferred_screen} drift=${s8.drift}`);

  // === claim 409 says why + what next ===================================
  const wQ = display("dev-q", "", "lab-q");
  const pendQ = await wQ.waitFor("pending");
  const clHeld = await post("/claim", { sid: pendQ.sid, name: "screen-9" });
  check("claim on live-held name 409s with reason + next",
    clHeld.status === 409 && clHeld.data.held_by === "live socket" &&
      /release/.test(clHeld.data.next || ""),
    `status=${clHeld.status} next=${clHeld.data.next || "-"}`);
  wQ.terminate();

  // === LIFECYCLE: disconnect -> reconnecting(age) + flap metric ========
  const t0 = Date.now();
  wP.terminate();
  await sleep(300);
  s9 = await screenEntry(9);
  check("dead socket derives reconnecting + reclaim countdown",
    s9.lifecycle === "reconnecting" &&
      s9.reclaim_in_s > 0 && s9.reclaim_in_s <= 60,
    `lifecycle=${s9.lifecycle} reclaim_in=${s9.reclaim_in_s}`);
  d = await displays();
  check("flap metric counts the abnormal close",
    d.health.flaps_24h >= 1 && !!d.health.last_flap &&
      d.health.reconnecting >= 1,
    `flaps=${d.health.flaps_24h} last=${d.health.last_flap} rec=${d.health.reconnecting}`);
  check("disconnect event logged with code",
    await hasEvent("disconnect", (e) => e.screen === 9 && e.abnormal));

  // sweep refuses a LIVE screen with a next action
  const swLive = await post("/sweep", { screen: 8 });
  check("sweep on live screen 409s with next action",
    swLive.status === 409 && !!swLive.data.next,
    `status=${swLive.status} next=${swLive.data.next || "-"}`);

  // === BENCH: disconnect -> rebound (self-heal path) ===================
  const wP2 = display("dev-x", paired.api_key, "lab-ipad");
  const reg2 = await wP2.waitFor("registered");
  const recoverMs = Date.now() - t0;
  console.log(`BENCH  disconnect->rebound ${recoverMs}ms ` +
    `(incl. 300ms observation delay; target self-heal <60s)`);
  check("reconnect rebinds same screen+name (self-heal)",
    reg2.screen === 9 && (await screenEntry(9)).connected === true &&
      recoverMs < 60000,
    `screen=${reg2.screen} recover=${recoverMs}ms`);
  check("rebind register event logged",
    await hasEvent("register", (e) => e.screen === 9 && e.rebind === true));

  // === RECOVERY: release answers with the tombstone note ===============
  const rel9 = await post("/release", { screen: 9 });
  check("release returns tombstone note + until",
    rel9.status === 200 && /reserved 30d for reclaim/.test(rel9.data.note || "") &&
      !!rel9.data.tombstone_until,
    `status=${rel9.status} note=${rel9.data.note || "-"}`);
  const unp = await wP2.waitFor("unpaired", () => true, 3000)
    .catch(() => null);
  check("released display told why (reason=released)",
    !!unp && unp.reason === "released",
    unp ? `reason=${unp.reason}` : "no unpaired msg");
  d = await displays();
  check("released name in tombstone list + health",
    (d.released || []).some((t) => t.name === "screen-9") &&
      d.health.released >= 2,
    `released=${(d.released || []).map((t) => t.name).join(",")}`);
  const relAgain = await post("/release", { screen: 9 });
  check("release of unknown screen 404s with next",
    relAgain.status === 404 && !!relAgain.data.next,
    `status=${relAgain.status}`);

  // === AUDIT: the timeline caught the whole journey ====================
  const kinds = new Set((await eventsOf()).map((e) => e.kind));
  check("timeline has claim/register/disconnect/sweep/release/dismiss-ish",
    ["pending", "claim", "register", "disconnect", "sweep", "release"]
      .every((k) => kinds.has(k)),
    [...kinds].join(","));

  wB.terminate();
  wP2.terminate();

  // === LIFECYCLE: live socket + silent app derives stale ===============
  // second relay spawn with a 400ms silence window — the zombie case the
  // 2026-10-22 live fleet showed (connected:true + 6-day-old last_seen)
  const reg2File = `/tmp/vcast-ux2-registry-${process.pid}.json`;
  fs.rmSync(reg2File, { force: true });
  const relay2 = spawn("node", [SERVER], {
    env: {
      ...process.env,
      INPUT_BRIDGE_PORT: "13015",
      INPUT_BRIDGE_BIND: "127.0.0.1",
      ADA_AUTH_URL: `http://127.0.0.1:${AUTH_PORT}`,
      VCAST_REGISTRY: reg2File,
      VCAST_EVENTS: `/tmp/vcast-ux2-events-${process.pid}.json`,
      VCAST_STALE_SEEN_MS: "400",
      VCAST_SWEEP_MS: "60000",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  try {
    relay2.stdout.on("data", () => {});
    relay2.stderr.on("data", () => {});
    await sleep(700);
    const wZ = new WebSocket("ws://127.0.0.1:13015/ws");
    const inbox = [];
    wZ.on("error", () => {});
    wZ.on("message", (raw) => inbox.push(JSON.parse(raw.toString())));
    await new Promise((res) => wZ.on("open", res));
    wZ.send(JSON.stringify({
      type: "register-display", api_key: "key-a", label: "z", device_id: "z",
    }));
    await new Promise((res, rej) => {
      const t = setTimeout(() => rej(new Error("no registered")), 5000);
      const p = setInterval(() => {
        if (inbox.some((m) => m.type === "registered")) {
          clearTimeout(t); clearInterval(p); res();
        }
      }, 20);
    });
    const snap = async () => {
      const r = await fetch("http://127.0.0.1:13015/displays");
      const dd = await r.json();
      return dd.screens.find((s) => s.screen === 9);
    };
    check("fresh register is not silent-stale",
      (await snap()).lifecycle !== "stale");
    await sleep(600);                    // past the 400ms silence window
    const z1 = await snap();
    check("silent live socket derives stale",
      z1.lifecycle === "stale" && z1.silent_socket === true &&
        z1.connected === true,
      `lifecycle=${z1.lifecycle} silent=${z1.silent_socket} conn=${z1.connected}`);
    wZ.send(JSON.stringify({ type: "state", state: "idle", detail: "" }));
    await sleep(150);
    check("a fresh report clears silent-stale",
      (await snap()).lifecycle === "idle");
    wZ.terminate();
  } finally {
    relay2.kill();
    fs.rmSync(reg2File, { force: true });
    fs.rmSync(`/tmp/vcast-ux2-events-${process.pid}.json`, { force: true });
  }
} finally {
  relay.kill();
  auth.close();
  fs.rmSync(regFile, { force: true });
  fs.rmSync(evFile, { force: true });
}
process.exit(failures.length ? 1 : 0);
