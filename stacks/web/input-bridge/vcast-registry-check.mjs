#!/usr/bin/env node
// vcast-registry-check — exercises the 2026-10-09 registry-bug fixes
// against the real server.mjs on loopback (stubbed ada auth):
//
//   1. dead-entry reclaim: ws drop leaves the entry for GRACE_MS and a
//      rebind takes the same slot; past grace the sweep deletes it.
//   2. claim honoring: /claim {name:screen-N} on a DEAD holder rebinds
//      slot N (never drifts to lowest-free); a LIVE different-name
//      holder still deflects to lowest-free; want_screen alternates work.
//   3. release tombstone: /release deletes the entry AND blocks
//      resurrection — a zombie's late state write can't recreate it and
//      its re-register gets "unpaired"; a fresh /claim lifts the
//      tombstone.
//
//   node vcast-registry-check.mjs [path/to/server.mjs]
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
const AUTH_PORT = 13993;
const RELAY_PORT = 13012;
const GRACE_MS = 500;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const failures = [];
function check(name, cond, detail = "") {
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
  if (!cond) failures.push(name);
}

// --- stub ada auth: admin key "adm"; key-name map; keys POST/DELETE -----
const keyNames = { adm: "admin", "key-s7": "screen-7", "key-custom": "loft-tv" };
const issued = new Set();
let mintCounter = 0;
const auth = http.createServer((req, res) => {
  const u = new URL(req.url, "http://x");
  if (u.pathname === "/api/auth/status") {
    const name = keyNames[u.searchParams.get("api_key")] || null;
    res.writeHead(200, { "content-type": "application/json" });
    return res.end(JSON.stringify({ authenticated: !!name, name }));
  }
  if (u.pathname === "/api/auth/keys" && req.method === "POST") {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      const name = JSON.parse(body || "{}").name;
      if (issued.has(name)) {            // stale key pins the name
        res.writeHead(409, { "content-type": "application/json" });
        return res.end(JSON.stringify({ error: "conflict" }));
      }
      issued.add(name);
      const tok = `tok${++mintCounter}`;
      keyNames[`key-${tok}`] = name;
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({
        name, redeem_url: `http://127.0.0.1:${AUTH_PORT}/redeem/${tok}`,
      }));
    });
    return;
  }
  if (u.pathname.startsWith("/api/auth/keys/") && req.method === "DELETE") {
    // frees the name for re-mint, but the OLD key keeps resolving — a
    // revoke that lagged downstream; the tombstone is what must block
    // resurrection, not the ada delete
    issued.delete(decodeURIComponent(u.pathname.split("/").pop()));
    res.writeHead(200, { "content-type": "application/json" });
    return res.end(JSON.stringify({ ok: true }));
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

const regFile = `/tmp/vcast-registry-${process.pid}.json`;
fs.rmSync(regFile, { force: true });
const relay = spawn("node", [SERVER], {
  env: {
    ...process.env,
    INPUT_BRIDGE_PORT: String(RELAY_PORT),
    INPUT_BRIDGE_BIND: "127.0.0.1",
    ADA_AUTH_URL: `http://127.0.0.1:${AUTH_PORT}`,
    ADA_ADMIN_KEY: "adm",
    VCAST_REGISTRY: regFile,
    VCAST_REDEEM_HOSTS: "127.0.0.1",
    VCAST_GRACE_MS: String(GRACE_MS),
    VCAST_SWEEP_MS: "150",
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
const displays = async () =>
  (await apiStatus("/displays")).data;
const screenEntry = async (n) =>
  (await displays()).screens.find((s) => s.screen === n);

function display(deviceId, apiKey = "", label = "reg-check") {
  const ws = new WebSocket(`ws://127.0.0.1:${RELAY_PORT}/ws`);
  const inbox = [];
  ws.on("error", () => {});   // released sockets get closed mid-flow
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
  // --- 1. claim honoring: fresh claim for screen-6 lands on 6 -----------
  const d6 = display("dev-6");
  const pend6 = await d6.waitFor("pending");
  const claim6 = await post("/claim", { sid: pend6.sid, name: "screen-6" });
  check("claim screen-6 honored when free",
    claim6.status === 200 && claim6.data.screen === 6,
    `status=${claim6.status} screen=${claim6.data.screen}`);
  const paired6 = await d6.waitFor("paired");
  d6.send(JSON.stringify({
    type: "register-display", api_key: paired6.api_key, label: "dev6" }));
  const reg6 = await d6.waitFor("registered");
  check("registered on screen 6", reg6.screen === 6, `screen=${reg6.screen}`);

  // --- 2. dead-entry reclaim: ws drop keeps the entry for the grace -----
  d6.terminate();
  await sleep(200);                       // < GRACE_MS
  let s6 = await screenEntry(6);
  check("dead entry retained during grace",
    !!s6 && s6.connected === false && !!s6.disconnected_at,
    s6 ? `connected=${s6.connected} dead_at=${!!s6.disconnected_at}` : "gone");

  // --- 3. rebind inside the grace window takes the same slot ------------
  const d6b = display("dev-6", paired6.api_key, "dev6");
  const reg6b = await d6b.waitFor("registered");
  check("rebind in grace re-takes screen 6", reg6b.screen === 6,
    `screen=${reg6b.screen}`);
  d6b.terminate();
  await sleep(GRACE_MS + 500);            // past grace + a sweep tick
  s6 = await screenEntry(6);
  check("entry freed after grace expiry", !s6,
    s6 ? `still present connected=${s6.connected}` : "swept");

  // --- 4. /claim on a DEAD same-name holder rebinds instead of drifting --
  const d6c = display("dev-6c", paired6.api_key, "dev6");
  const reg6c = await d6c.waitFor("registered");
  check("re-register re-creates on pinned slot", reg6c.screen === 6,
    `screen=${reg6c.screen}`);
  d6c.terminate();
  await sleep(200);                       // dead-in-grace entry on slot 6
  const dX = display("dev-x");            // new pending display
  const pendX = await dX.waitFor("pending");
  let claimX = await post("/claim", { sid: pendX.sid, name: "screen-6" });
  if (claimX.status === 409)              // ada key still pins the name —
    claimX = await post("/claim",         // force re-mint (client contract)
      { sid: pendX.sid, name: "screen-6", force: true });
  check("claim screen-6 over dead holder stays on 6 (no drift)",
    claimX.status === 200 && claimX.data.screen === 6,
    `status=${claimX.status} screen=${claimX.data.screen}`);
  dX.terminate();

  // --- 5. a LIVE different-name holder deflects to lowest-free ----------
  const dC = display("dev-c", "key-custom", "loft");
  const regC = await dC.waitFor("registered");
  const heldSlot = regC.screen;
  const dY = display("dev-y");
  const pendY = await dY.waitFor("pending");
  const claimY = await post("/claim",
    { sid: pendY.sid, name: `screen-${heldSlot}` });
  check("claim on live-held slot falls to lowest free",
    claimY.status === 200 && claimY.data.screen !== heldSlot,
    `held=${heldSlot} got=${claimY.data.screen}`);
  dY.terminate();

  // --- 6. want_screen alternate field ------------------------------------
  const d9 = display("dev-9");
  const pend9 = await d9.waitFor("pending");
  const claim9 = await post("/claim", { sid: pend9.sid, want_screen: 9 });
  check("want_screen honored when free",
    claim9.status === 200 && claim9.data.screen === 9,
    `screen=${claim9.data.screen}`);
  d9.terminate();

  // --- 7. release tombstone: zombie writes/registers can't resurrect ----
  const d7 = display("dev-7", "key-s7", "loft7");
  const reg7 = await d7.waitFor("registered");
  check("seeded key registered screen 7", reg7.screen === 7);
  const rel = await post("/release", { screen: 7, admin_key: "adm" });
  check("release ok", rel.status === 200, `status=${rel.status}`);
  // the live socket gets unpaired + a clean close
  const unp0 = await d7.waitFor("unpaired", () => true, 3000)
    .catch(() => null);
  check("released display receives unpaired", !!unp0);
  await sleep(300);
  let s7 = await screenEntry(7);
  check("release deleted the entry", !s7, s7 ? "still present" : "gone");
  d7.terminate();
  // the zombie path: a NEW socket registering with the still-resolving
  // stale key must be refused — the tombstone, not the ada revoke, is
  // what blocks resurrection (the stub leaves key-s7 valid on purpose)
  const d7z = display("dev-7z", "key-s7", "loft7");
  const unp = await d7z.waitFor("unpaired", () => true, 3000)
    .catch(() => null);
  check("tombstoned re-register gets unpaired", !!unp,
    `inbox=${JSON.stringify(d7z.inbox.map((m) => m.type))}`);
  try { d7z.send(JSON.stringify({ type: "state", state: "nav", detail: "0:x" })); } catch (e) {}
  await sleep(300);
  s7 = await screenEntry(7);
  check("dead-socket writes did not resurrect screen 7", !s7,
    s7 ? `state=${s7.state}` : "still gone");
  d7z.terminate();

  // --- 8. a fresh /claim lifts the tombstone ------------------------------
  const d7b = display("dev-7b");
  const pend7b = await d7b.waitFor("pending");
  const claim7b = await post("/claim", { sid: pend7b.sid, name: "screen-7" });
  check("re-claim of tombstoned name ok",
    claim7b.status === 200 && claim7b.data.screen === 7,
    `status=${claim7b.status} screen=${claim7b.data.screen}`);
  const paired7b = await d7b.waitFor("paired");
  d7b.send(JSON.stringify({
    type: "register-display", api_key: paired7b.api_key, label: "dev7b" }));
  const reg7b = await d7b.waitFor("registered");
  check("re-claimed screen 7 registers", reg7b.screen === 7,
    `screen=${reg7b.screen}`);
  d7b.terminate();
} finally {
  relay.kill();
  auth.close();
  fs.rmSync(regFile, { force: true });
}
process.exit(failures.length ? 1 : 0);
