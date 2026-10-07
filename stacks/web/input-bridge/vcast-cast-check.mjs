#!/usr/bin/env node
// vcast-cast-check — exercises the manual cast flow end-to-end against the
// real server.mjs on a loopback port with a stubbed ADA_AUTH_URL:
//
//   ws display -> register (no key) -> pending sid -> /pair-info -> /claim
//   -> display gets api_key over ws -> re-register -> registered
//   -> /pub play + image -> delivered -> capture lease set/interrupt/clear
//   -> stop -> ws reconnect -> lastCast replay restores the cast
//
// Also measures claim->registered and pub->play latency — the vcast-app
// card metric is pair->play <10s on a fresh device.
//
// The capture-lease section is the repo-side contract for the ada-pi
// cast_interrupt_gate scenario: the relay itself never gates interrupts
// (Ada's tool_runner reads /capture before casting); here we prove the
// lease API the gate depends on works and that delivery is unaffected.
//
//   node vcast-cast-check.mjs [path/to/server.mjs]
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
const AUTH_PORT = 13992;
const RELAY_PORT = 13011;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const failures = [];
function check(name, cond, detail = "") {
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
  if (!cond) failures.push(name);
}

// --- stub ada auth: admin key -> admin user; minted keys -> screen-N ----
const keyNames = { adm: "admin", "key-screen9": "screen-9" };
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
      const name = JSON.parse(body || "{}").name || `screen-${++mintCounter}`;
      const tok = `tok${++mintCounter}`;
      keyNames[`key-${tok}`] = name;
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({
        name, redeem_url: `http://127.0.0.1:${AUTH_PORT}/redeem/${tok}`,
      }));
    });
    return;
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

const regFile = `/tmp/vcast-cast-registry-${process.pid}.json`;
fs.rmSync(regFile, { force: true });
// preseed a DRIFTED binding: name "screen-9" parked on slot 2 — the
// migration-scramble state (registerDisplay used to take lowest-free and
// never heal it). The register below must move it home to slot 9.
fs.writeFileSync(regFile, JSON.stringify({ screens: {
  "2": { name: "screen-9", label: "drifted",
         assigned_at: "2026-10-01T00:00:00Z" },
} }));
const relay = spawn("node", [SERVER], {
  env: {
    ...process.env,
    INPUT_BRIDGE_PORT: String(RELAY_PORT),
    INPUT_BRIDGE_BIND: "127.0.0.1",
    ADA_AUTH_URL: `http://127.0.0.1:${AUTH_PORT}`,
    ADA_ADMIN_KEY: "adm",
    VCAST_REGISTRY: regFile,
    VCAST_REDEEM_HOSTS: "127.0.0.1",
  },
  stdio: ["ignore", "pipe", "pipe"],
});
relay.stdout.on("data", (d) => process.stderr.write(`[relay] ${d}`));
relay.stderr.on("data", (d) => process.stderr.write(`[relay] ${d}`));
await sleep(800);

const api = async (p, opts) =>
  (await fetch(`http://127.0.0.1:${RELAY_PORT}${p}`, opts)).json()
    .then((data) => data)
    .catch(() => ({}));
const apiStatus = async (p, opts) => {
  const r = await fetch(`http://127.0.0.1:${RELAY_PORT}${p}`, opts);
  return { status: r.status, data: await r.json().catch(() => ({})) };
};
const post = (p, body) =>
  apiStatus(p, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });

// a minimal display client: connects ws, registers, records messages
function display(deviceId, apiKey = "", label = "check-display") {
  const ws = new WebSocket(`ws://127.0.0.1:${RELAY_PORT}/ws`);
  const inbox = [];
  ws.on("message", (raw) => inbox.push(JSON.parse(raw.toString())));
  ws.on("open", () =>
    ws.send(JSON.stringify({
      type: "register-display", api_key: apiKey, label, device_id: deviceId,
    })));
  ws.waitFor = (type, pred = () => true, ms = 5000) => new Promise((res, rej) => {
    const t0 = Date.now();
    const t = setTimeout(() => rej(new Error(`timeout waiting ${type}`)), ms);
    const poll = setInterval(() => {
      const m = inbox.find((m) => m.type === type && pred(m));
      if (m) {
        clearTimeout(t); clearInterval(poll);
        m._waitedMs = Date.now() - t0;
        res(m);
      }
    }, 20);
  });
  ws.clearInbox = () => (inbox.length = 0);
  ws.inbox = inbox;
  return ws;
}
const inboxTypes = (w) => w.inbox.map((m) => m.type);

let SCREEN = 0;
try {
  // --- unpaired display -> pending sid --------------------------------------
  const d = display("checkdev-1");
  const pend = await d.waitFor("pending");
  check("unpaired display gets pending sid", !!pend.sid, `sid=${pend.sid}`);

  const { status: piStatus, data: pi } =
    await apiStatus(`/pair-info?sid=${pend.sid}`);
  check("/pair-info resolves sid", piStatus === 200 && pi.sid === pend.sid,
    `status=${piStatus} label=${pi.label}`);

  // --- claim (phone-side of pair.html) -> api_key pushed over ws ------------
  const tClaim = Date.now();
  const claim = await post("/claim", { sid: pend.sid });
  check("claim ok", claim.status === 200 && claim.data.screen > 0,
    `status=${claim.status} screen=${claim.data.screen}`);
  const paired = await d.waitFor("paired");
  check("display received api_key over ws", !!paired.api_key);

  // --- display re-registers with the key -> registered ----------------------
  d.send(JSON.stringify({
    type: "register-display", api_key: paired.api_key,
    label: "check-display", device_id: "checkdev-1",
  }));
  const reg = await d.waitFor("registered");
  SCREEN = reg.screen;
  const claimToReg = Date.now() - tClaim;
  check("re-register lands on claimed screen", SCREEN === claim.data.screen,
    `screen=${SCREEN}`);
  check("claim->registered < 10s (pair->play budget)", claimToReg < 10000,
    `${claimToReg}ms (claim includes stub ada keys+redeem hops)`);

  // --- manual cast: play + image --------------------------------------------
  const tPlay = Date.now();
  await post("/pub", { screen: SCREEN,
    msg: { type: "play", url: "https://x/cam.m3u8" } });
  const play = await d.waitFor("play");
  check("play delivered", play.url === "https://x/cam.m3u8",
    `pub->delivery ${Date.now() - tPlay}ms`);

  await post("/pub", { screen: SCREEN,
    msg: { type: "image", url: "https://x/snap.png", pane: 1 } });
  const img = await d.waitFor("image");
  check("image to pane 1 delivered", img.pane === 1);

  // --- capture lease: the cast_interrupt_gate contract ----------------------
  await post("/capture", { screen: SCREEN, source: "cam", active: true });
  const cap = await api(`/capture?screen=${SCREEN}`);
  check("capture lease recorded", cap.active === true && cap.source === "cam",
    `capture=${JSON.stringify(cap)}`);

  const interrupt = await post("/pub", { screen: SCREEN,
    msg: { type: "play", url: "https://x/interrupt.m3u8" } });
  check("relay still delivers during lease (gate lives in Ada, not relay)",
    interrupt.status === 200 && interrupt.data.delivered === 1);
  const play2 = await d.waitFor("play",
    (m) => m.url === "https://x/interrupt.m3u8", 3000).catch(() => null);
  check("interrupt cast reached the display", !!play2);

  await post("/capture", { screen: SCREEN, active: false });
  const cap2 = await api(`/capture?screen=${SCREEN}`);
  check("capture lease cleared", cap2.active === false);

  // --- stop + reconnect replay ----------------------------------------------
  await post("/pub", { screen: SCREEN, msg: { type: "stop" } });
  await d.waitFor("stop");
  check("stop delivered", true);

  // ws flap: lastCast replay must re-render the last cast on re-register
  d.terminate();
  await sleep(300);
  await post("/pub", { screen: SCREEN,
    msg: { type: "play", url: "https://x/last.m3u8" } });
  await sleep(200);
  const d2 = display("checkdev-1", paired.api_key);
  const reg2 = await d2.waitFor("registered");
  check("reconnect re-registers same screen", reg2.screen === SCREEN);
  const replay = await d2.waitFor("play", () => true, 6000).catch(() => null);
  check("lastCast replay restores play after flap",
    replay && replay.url === "https://x/last.m3u8",
    replay ? `url=${replay.url}` : `inbox=${JSON.stringify(inboxTypes(d2))}`);
  d2.terminate();

  // --- slot pinning: screen-N names take slot N on ANY attach path ------
  // the seeded "screen-9" entry sits on slot 2; a display registering with
  // its key must re-home it to slot 9 (registerDisplay only ever took
  // lowest-free before — that is how the 2026-10-06 migration scramble
  // put screen-6 on slot 1 and stranded {real_screen} casts).
  const d9 = display("checkdev-9", "key-screen9", "drifted-9");
  const reg9 = await d9.waitFor("registered");
  check("register re-homes drifted name to screen-N slot",
    reg9.screen === 9, `screen=${reg9.screen}`);
  const drifted = (await api("/displays")).screens
    .find((s) => s.screen === 2);
  check("old slot released", !drifted || drifted.name !== "screen-9",
    drifted ? `slot2=${drifted.name}` : "slot2 empty");
  d9.terminate();
} finally {
  relay.kill();
  auth.close();
  fs.rmSync(regFile, { force: true });
}
process.exit(failures.length ? 1 : 0);
