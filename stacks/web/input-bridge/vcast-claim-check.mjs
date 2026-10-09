#!/usr/bin/env node
// vcast-claim-check — exercises the tombstone -> resurrect -> redeem claim
// path (card vcast-claim-tombstone) against the real server.mjs on
// loopback with a stubbed ada that models member-invite key states
// (approved/pending/revoked — DELETE revokes, the name stays taken):
//
//   1. /release revokes the ada key AND tombstones the name; a plain
//      /api/auth/keys POST on it 409s.
//   2. /claim {name} auto-resurrects through the invite chain
//      (POST /api/auth/invites -> POST /api/auth/keys/{name}/approve ->
//      POST /api/auth/invites/{name} -> redeem_url) — one claim call, no
//      manual ada-auth steps, no force flag — and the display pairs +
//      registers on the same name/screen.
//   3. Guard: resurrect only applies to /^screen-\d+$/ — a tombstoned
//      member name still 409s (its resurrect path is the deliberate
//      invite flow on the keys card).
//   4. Rival-claimant race: claims are atomic server-side — two pending
//      displays racing the same tombstoned name cannot both pair; the
//      loser gets 409 (explicit name) or the next free slot
//      (want_screen).
//   5. Live-held names are untouchable: claiming a name a connected
//      display owns 409s and never revokes its key — the force-loop
//      re-tombstone is gone (body.force is ignored).
//
//   node vcast-claim-check.mjs [path/to/server.mjs]
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
const AUTH_PORT = 13994;
const RELAY_PORT = 13013;
const GRACE_MS = 500;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const failures = [];
function check(name, cond, detail = "") {
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
  if (!cond) failures.push(name);
}

// --- stub ada auth: member-invite key lifecycle --------------------------
// keys keep their name after DELETE (revoke != delete) — the premise that
// makes plain re-mint 409 and the resurrect chain necessary. Revoked keys
// still resolve on /status (the lag model the tombstone guards).
const keyNames = { adm: "admin", "key-s7": "screen-7", "key-loft": "loft-tv" };
const adaKeys = new Map();   // name -> {state: approved|pending|revoked}
adaKeys.set("screen-7", { state: "approved" });
adaKeys.set("loft-tv", { state: "approved" });
const redeemNames = new Map(); // redeem token -> key name
let mintCounter = 0;
const adaCalls = [];         // ordered ada-side audit log for assertions
const readReq = (req) => new Promise((r) => {
  let b = "";
  req.on("data", (c) => (b += c));
  req.on("end", () => r(JSON.parse(b || "{}")));
});
const auth = http.createServer(async (req, res) => {
  const u = new URL(req.url, "http://x");
  const j = (code, obj) => {
    res.writeHead(code, { "content-type": "application/json" });
    res.end(JSON.stringify(obj));
  };
  if (u.pathname === "/api/auth/status") {
    const name = keyNames[u.searchParams.get("api_key")] || null;
    return j(200, { authenticated: !!name, name });
  }
  if (u.pathname === "/api/auth/keys" && req.method === "POST") {
    const { name } = await readReq(req);
    adaCalls.push(`keys:${name}`);
    if (adaKeys.has(name)) return j(409, { error: "exists" });
    adaKeys.set(name, { state: "approved" });
    const tok = `tok${++mintCounter}`;
    redeemNames.set(tok, name);
    return j(200, {
      name, redeem_url: `http://127.0.0.1:${AUTH_PORT}/redeem/${tok}`,
    });
  }
  const keyM = u.pathname.match(/^\/api\/auth\/keys\/([^/]+)(\/approve)?$/);
  if (keyM && req.method === "DELETE") {
    const name = decodeURIComponent(keyM[1]);
    adaCalls.push(`delete:${name}`);
    const k = adaKeys.get(name);
    if (k) k.state = "revoked";            // name stays taken
    return j(200, { ok: true });
  }
  if (keyM && keyM[2] && req.method === "POST") {
    const name = decodeURIComponent(keyM[1]);
    adaCalls.push(`approve:${name}`);
    const k = adaKeys.get(name);
    if (!k) return j(404, { error: "no such key" });
    k.state = "approved";
    return j(200, { ok: true });
  }
  if (u.pathname === "/api/auth/invites" && req.method === "POST") {
    const { name } = await readReq(req);
    adaCalls.push(`invite:${name}`);
    let k = adaKeys.get(name);
    if (!k) { k = {}; adaKeys.set(name, k); }
    if (k.state !== "approved") k.state = "pending";
    return j(200, { invite_url: `http://127.0.0.1:${AUTH_PORT}/i/x` });
  }
  const invM = u.pathname.match(/^\/api\/auth\/invites\/([^/]+)$/);
  if (invM && req.method === "POST") {
    const name = decodeURIComponent(invM[1]);
    adaCalls.push(`mint:${name}`);
    const k = adaKeys.get(name);
    if (!k || k.state !== "approved") return j(409, { error: "not approved" });
    const tok = `tok${++mintCounter}`;
    redeemNames.set(tok, name);
    return j(200, {
      name, redeem_url: `http://127.0.0.1:${AUTH_PORT}/redeem/${tok}`,
    });
  }
  if (u.pathname.startsWith("/redeem/")) {
    const tok = u.pathname.split("/").pop();
    const name = redeemNames.get(tok);
    if (!name) return j(410, { error: "burned" });
    keyNames[`key-${tok}`] = name;
    res.writeHead(302, { location: `/apps/vcast/?api_key=key-${tok}` });
    return res.end();
  }
  return j(404, {});
});
await new Promise((r) => auth.listen(AUTH_PORT, "127.0.0.1", r));

const regFile = `/tmp/vcast-claim-registry-${process.pid}.json`;
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
const displays = async () => (await apiStatus("/displays")).data;
const screenEntry = async (n) =>
  (await displays()).screens.find((s) => s.screen === n);

function display(deviceId, apiKey = "", label = "claim-check") {
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
const pendingSid = async (devId) => {
  const ws = display(devId);
  const p = await ws.waitFor("pending");
  return { ws, sid: p.sid };
};
const callsFor = (name) => adaCalls.filter((c) => c.endsWith(`:${name}`));

try {
  // --- 1. seed + release: screen-7 tombstoned, ada key revoked ---------
  const d7 = display("dev-7", "key-s7", "loft7");
  const reg7 = await d7.waitFor("registered");
  check("seeded key registered screen 7", reg7.screen === 7);
  const rel = await post("/release", { screen: 7, admin_key: "adm" });
  check("release ok", rel.status === 200, `status=${rel.status}`);
  await d7.waitFor("unpaired", () => true, 3000).catch(() => null);
  d7.terminate();
  check("release revoked the ada key (name still taken)",
    adaKeys.get("screen-7").state === "revoked" && adaKeys.has("screen-7"));

  // --- 2. tombstone -> /claim {name} -> resurrect -> redeem -> pair ----
  const { ws: d7b, sid: sid7b } = await pendingSid("dev-7b");
  adaCalls.length = 0;
  const claim7 = await post("/claim", { sid: sid7b, name: "screen-7" });
  check("claim on tombstoned name succeeds without manual ada calls",
    claim7.status === 200 && claim7.data.screen === 7,
    `status=${claim7.status} screen=${claim7.data.screen}`);
  check("resurrect chain ran in order (invite -> approve -> mint)",
    JSON.stringify(callsFor("screen-7")) ===
      JSON.stringify(["keys:screen-7", "invite:screen-7",
                      "approve:screen-7", "mint:screen-7"]),
    adaCalls.join(","));
  const paired7b = await d7b.waitFor("paired");
  check("resurrected redeem pushes api_key to the display",
    !!paired7b.api_key && paired7b.name === "screen-7");
  d7b.send(JSON.stringify({
    type: "register-display", api_key: paired7b.api_key, label: "dev7b" }));
  const reg7b = await d7b.waitFor("registered");
  check("resurrected name registers back on screen 7 (tombstone lifted)",
    reg7b.screen === 7, `screen=${reg7b.screen}`);

  // --- 3. guard: member names keep tombstone semantics -----------------
  const relL = await post("/release", { name: "loft-tv", admin_key: "adm" });
  check("member name release ok", relL.status === 200);
  const { ws: dL, sid: sidL } = await pendingSid("dev-l");
  adaCalls.length = 0;
  const claimL = await post("/claim", { sid: sidL, name: "loft-tv" });
  check("non-screen tombstoned name stays a hard 409",
    claimL.status === 409, `status=${claimL.status}`);
  check("resurrect chain NOT attempted for member names",
    !adaCalls.some((c) => /^(invite|approve|mint):loft-tv$/.test(c)),
    adaCalls.join(","));
  dL.terminate();

  // --- 4. rival-claimant race on the same tombstoned name --------------
  keyNames["key-9"] = "screen-9";
  adaKeys.set("screen-9", { state: "approved" });
  const d9 = display("dev-9", "key-9", "lab9");
  const reg9 = await d9.waitFor("registered");
  check("seeded screen-9", reg9.screen === 9);
  await post("/release", { screen: 9, admin_key: "adm" });
  d9.terminate();
  const { ws: dA, sid: sidA } = await pendingSid("dev-a");
  const { ws: dB, sid: sidB } = await pendingSid("dev-b");
  const [claimA, claimB] = await Promise.all([
    post("/claim", { sid: sidA, name: "screen-9" }),
    post("/claim", { sid: sidB, name: "screen-9" }),
  ]);
  const outcomes = [claimA.status, claimB.status].sort();
  check("racing claims: exactly one wins, loser gets 409",
    outcomes[0] === 200 && outcomes[1] === 409,
    `A=${claimA.status} B=${claimB.status}`);
  const winnerWs = claimA.status === 200 ? dA : dB;
  const loserWs = claimA.status === 200 ? dB : dA;
  const pairedW = await winnerWs.waitFor("paired", () => true, 3000)
    .catch(() => null);
  const pairedL = loserWs.inbox.find((m) => m.type === "paired") || null;
  check("only the winner's display received a paired key",
    !!pairedW && !pairedL);
  winnerWs.send(JSON.stringify({
    type: "register-display",
    api_key: pairedW ? pairedW.api_key : "", label: "winner" }));
  const regW = await winnerWs.waitFor("registered");
  check("winner registers on screen 9", regW.screen === 9,
    `screen=${regW.screen}`);

  // --- 5. number-derived claim deflects to the next free slot ----------
  const { ws: dC, sid: sidC } = await pendingSid("dev-c");
  const claimC = await post("/claim", { sid: sidC, want_screen: 9 });
  check("want_screen rival takes next free slot",
    claimC.status === 200 && claimC.data.screen !== 9,
    `status=${claimC.status} screen=${claimC.data.screen}`);
  dC.terminate();

  // --- 6. live-held names: no revoke, no re-tombstone ------------------
  adaCalls.length = 0;
  const { ws: dX, sid: sidX } = await pendingSid("dev-x");
  const claimX = await post("/claim",
    { sid: sidX, name: "screen-7", force: true });
  check("claim on a live-held name 409s even with force",
    claimX.status === 409, `status=${claimX.status}`);
  check("live display's ada key was never touched",
    !adaCalls.some((c) => /^(delete|keys|invite|approve|mint):screen-7$/.test(c)),
    adaCalls.join(","));
  const s7 = await screenEntry(7);
  check("live display still owns screen 7",
    !!s7 && s7.connected === true, s7 ? `connected=${s7.connected}` : "gone");
  const unpX = await d7b.waitFor("unpaired", () => true, 800)
    .catch(() => null);
  check("live display was not unpaired by the rival claim", !unpX);
  dX.terminate(); loserWs.terminate(); winnerWs.terminate(); d7b.terminate();
} finally {
  relay.kill();
  auth.close();
  fs.rmSync(regFile, { force: true });
}
process.exit(failures.length ? 1 : 0);
