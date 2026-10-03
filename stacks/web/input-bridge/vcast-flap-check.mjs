#!/usr/bin/env node
// vcast-flap-check — exercises the stale-socket race that left /displays
// reporting idle/offline after an iPad websocket flap (2026-09-28 incident):
//
//   wsA registers -> reports state -> wsB re-registers the same screen
//   -> wsA's queued state report must NOT overwrite wsB's ground truth
//   -> wsA's close must NOT evict wsB from live[]
//
// Spawns the real server.mjs on a loopback port with a stubbed
// ADA_AUTH_URL (any key authenticates as screen-9), then drives two ws
// clients through the flap. Exit 0 = all invariants hold.
//
//   node vcast-flap-check.mjs [path/to/server.mjs]
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
const AUTH_PORT = 13991;
const RELAY_PORT = 13010;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const failures = [];
function check(name, cond, detail = "") {
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
  if (!cond) failures.push(name);
}

// --- stub ada auth: every api_key authenticates as screen-9 -----------------
const auth = http.createServer((req, res) => {
  if (req.url.startsWith("/api/auth/status")) {
    res.writeHead(200, { "content-type": "application/json" });
    return res.end(JSON.stringify({ authenticated: true, name: "screen-9" }));
  }
  res.writeHead(404, { "content-type": "application/json" });
  res.end("{}");
});
await new Promise((r) => auth.listen(AUTH_PORT, "127.0.0.1", r));

const regFile = `/tmp/vcast-flap-registry-${process.pid}.json`;
fs.rmSync(regFile, { force: true });
const relay = spawn("node", [SERVER], {
  env: {
    ...process.env,
    INPUT_BRIDGE_PORT: String(RELAY_PORT),
    INPUT_BRIDGE_BIND: "127.0.0.1",
    ADA_AUTH_URL: `http://127.0.0.1:${AUTH_PORT}`,
    VCAST_REGISTRY: regFile,
    VCAST_REDEEM_HOSTS: "127.0.0.1",
  },
  stdio: ["ignore", "pipe", "pipe"],
});
relay.stdout.on("data", (d) => process.stderr.write(`[relay] ${d}`));
relay.stderr.on("data", (d) => process.stderr.write(`[relay] ${d}`));
await sleep(800);

const open = () =>
  new Promise((res, rej) => {
    const w = new WebSocket(`ws://127.0.0.1:${RELAY_PORT}/ws`);
    w.on("open", () => res(w));
    w.on("error", rej);
  });
const waitType = (w, type, ms = 4000) =>
  new Promise((res, rej) => {
    const t = setTimeout(() => rej(new Error(`timeout waiting for ${type}`)), ms);
    const h = (raw) => {
      const m = JSON.parse(raw.toString());
      if (m.type === type) { clearTimeout(t); w.off("message", h); res(m); }
    };
    w.on("message", h);
  });
const send = (w, o) => w.send(JSON.stringify(o));
const displays = async () =>
  (await fetch(`http://127.0.0.1:${RELAY_PORT}/displays`)).json();
let SCREEN = 0;
const screenN = async () =>
  (await displays()).screens.find((s) => s.screen === SCREEN) || {};

try {
  // --- wsA registers and reports a real cast state --------------------------
  const wsA = await open();
  send(wsA, { type: "register-display", api_key: "k", label: "ipad" });
  const regA = await waitType(wsA, "registered");
  SCREEN = regA.screen;
  check("wsA registered", typeof SCREEN === "number" && SCREEN > 0,
    `screen=${SCREEN}`);
  send(wsA, { type: "state", state: "nav", detail: "0:/apps/camwall/?zone=x" });
  await sleep(300);
  let s = await screenN();
  check("wsA state reported", s.state === "nav" && s.connected === true,
    `state=${s.state} connected=${s.connected}`);

  // --- wsB re-registers the same screen (iPad flap) -------------------------
  const wsB = await open();
  send(wsB, { type: "register-display", api_key: "k", label: "ipad" });
  const regB = await waitType(wsB, "registered");
  check("wsB re-registered same screen", regB.screen === SCREEN,
    `screen=${regB.screen}`);
  send(wsB, { type: "state", state: "image", detail: "0:https://x/y.jpg" });
  await sleep(300);

  // --- zombie write: wsA's queued state report must not stick ---------------
  try { send(wsA, { type: "state", state: "idle" }); } catch (e) {}
  await sleep(400);
  s = await screenN();
  check("stale wsA state write ignored", s.state === "image",
    `state=${s.state}`);

  // --- zombie close: wsA's close must not evict live wsB --------------------
  try { wsA.terminate(); } catch (e) {}
  await sleep(400);
  s = await screenN();
  check("stale wsA close keeps wsB connected", s.connected === true,
    `connected=${s.connected}`);

  // --- live socket still owns the state path --------------------------------
  send(wsB, { type: "state", state: "nav", detail: "0:/apps/camwall/?zone=y" });
  await sleep(300);
  s = await screenN();
  check("live wsB state still accepted", s.state === "nav",
    `state=${s.state}`);

  // --- real disconnect is still honoured ------------------------------------
  wsB.terminate();
  await sleep(400);
  s = await screenN();
  check("wsB close marks screen offline", s.connected === false,
    `connected=${s.connected}`);
} finally {
  relay.kill();
  auth.close();
  fs.rmSync(regFile, { force: true });
}
process.exit(failures.length ? 1 : 0);
