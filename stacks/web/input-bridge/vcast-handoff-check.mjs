#!/usr/bin/env node
// vcast-handoff-check — exercises the headless<->claim lease handoff that
// broke on the 2026-10-06 idc01->idc03 relay move: a stale ada key pinned
// the screen-N name, /claim answered 409, and the headless client parked
// dead for days (no retry, no force, no persisted key). The real
// vcast-headless.mjs is driven against a loopback server.mjs with a
// stubbed ada that mimics the key-pin:
//
//   boot 1: register -> pending -> claim 409 (key exists) -> force claim
//           -> paired -> registered, key persisted to VCAST_KEY_FILE
//   boot 2: new process, persisted key -> registered WITHOUT /claim
//           (the fast reattach path — metric: attach <5s)
//
//   node vcast-handoff-check.mjs [path/to/server.mjs]
//
"use strict";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SERVER = process.argv[2] || path.join(HERE, "server.mjs");
const HEADLESS = path.join(HERE, "vcast-headless.mjs");
const AUTH_PORT = 13993;
const RELAY_PORT = 13012;
const SCREEN_NAME = "screen-5";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const failures = [];
function check(name, cond, detail = "") {
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
  if (!cond) failures.push(name);
}

// --- stub ada auth: keys persist; POST on an existing name -> 409 -------
const adaKeys = new Map();         // name -> {api_key}
let mintCounter = 0;
adaKeys.set(SCREEN_NAME, { api_key: `key-old-${SCREEN_NAME}` }); // stale pin
const auth = http.createServer((req, res) => {
  const u = new URL(req.url, "http://x");
  let body = "";
  req.on("data", (c) => (body += c));
  req.on("end", () => {
    if (u.pathname === "/api/auth/status") {
      const name = [...adaKeys.entries()]
        .find(([, k]) => k.api_key === u.searchParams.get("api_key"))?.[0]
        || (u.searchParams.get("api_key") === "adm" ? "admin" : null);
      res.writeHead(200, { "content-type": "application/json" });
      return res.end(JSON.stringify({ authenticated: !!name, name }));
    }
    if (u.pathname === "/api/auth/keys" && req.method === "POST") {
      const name = JSON.parse(body || "{}").name;
      if (adaKeys.has(name)) {
        res.writeHead(409, { "content-type": "application/json" });
        return res.end(JSON.stringify({ error: "exists" }));
      }
      const tok = `tok${++mintCounter}`;
      adaKeys.set(name, { api_key: `key-${tok}` });
      res.writeHead(200, { "content-type": "application/json" });
      return res.end(JSON.stringify({
        name, redeem_url: `http://127.0.0.1:${AUTH_PORT}/redeem/${tok}` }));
    }
    if (u.pathname.startsWith("/api/auth/keys/") && req.method === "DELETE") {
      adaKeys.delete(decodeURIComponent(u.pathname.split("/").pop()));
      res.writeHead(200, { "content-type": "application/json" });
      return res.end("{}");
    }
    if (u.pathname.startsWith("/redeem/")) {
      const tok = u.pathname.split("/").pop();
      res.writeHead(302, { location: `/apps/vcast/?api_key=key-${tok}` });
      return res.end();
    }
    res.writeHead(404, { "content-type": "application/json" });
    res.end("{}");
  });
});
await new Promise((r) => auth.listen(AUTH_PORT, "127.0.0.1", r));

const regFile = `/tmp/vcast-handoff-registry-${process.pid}.json`;
const keyFile = `/tmp/vcast-handoff-key-${process.pid}.txt`;
fs.rmSync(regFile, { force: true });
fs.rmSync(keyFile, { force: true });
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

// spawn vcast-headless and capture its log lines
function runHeadless() {
  const p = spawn("node", [HEADLESS,
    `ws://127.0.0.1:${RELAY_PORT}/ws`, `http://127.0.0.1:${RELAY_PORT}`], {
    env: {
      ...process.env,
      ADA_ADMIN_KEY: "adm",
      VCAST_NAME: SCREEN_NAME,
      VCAST_LABEL: "handoff-check",
      VCAST_DEV_ID: "handoff-check",
      VCAST_KEY_FILE: keyFile,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const lines = [];
  p.stdout.on("data", (d) => lines.push(...d.toString().split("\n")));
  p.stderr.on("data", (d) => lines.push(...d.toString().split("\n")));
  p.lines = lines;
  return p;
}
const waitFor = (p, re, ms = 15000) => new Promise((res, rej) => {
  const t0 = Date.now();
  const t = setInterval(() => {
    const hit = p.lines.find((l) => re.test(l));
    if (hit) { clearInterval(t); res({ line: hit, ms: Date.now() - t0 }); }
    else if (Date.now() - t0 > ms) {
      clearInterval(t);
      rej(new Error(`timeout ${ms}ms waiting for ${re} — saw: ` +
        p.lines.filter(Boolean).slice(-8).join(" | ")));
    }
  }, 50);
});

let h1;
try {
  // --- boot 1: 409 stale-key pin -> force claim -> registered ----------
  const t0 = Date.now();
  h1 = runHeadless();
  const reg = await waitFor(h1, /\[registered\] Screen #(\d+)/);
  const regScreen = parseInt(reg.line.match(/#(\d+)/)[1], 10);
  check("headless registered through stale-key pin", regScreen === 5,
    `screen=${regScreen} attach=${Date.now() - t0}ms`);
  const saw409 = h1.lines.some((l) => /\[claim\] 409/.test(l));
  check("claim hit 409 before force succeeded", saw409);
  check("api_key persisted to key file", fs.existsSync(keyFile),
    keyFile);
  h1.kill("SIGKILL");                 // unclean kill — the migration case
  await sleep(300);

  // --- boot 2: persisted key -> registered without claim ---------------
  const t1 = Date.now();
  const h2 = runHeadless();
  const reg2 = await waitFor(h2, /\[registered\] Screen #(\d+)/);
  const attachMs = Date.now() - t1;
  check("reattach lands same screen", parseInt(reg2.line.match(/#(\d+)/)[1], 10) === 5);
  check("reattach skipped claim entirely",
    !h2.lines.some((l) => /\[claim\]/.test(l)));
  check("reattach < 5s (headless attach budget)", attachMs < 5000,
    `${attachMs}ms`);
  h2.kill("SIGKILL");
} catch (e) {
  check("handoff flow", false, e.message);
} finally {
  try { h1?.kill("SIGKILL"); } catch {}
  relay.kill();
  auth.close();
  fs.rmSync(regFile, { force: true });
  fs.rmSync(keyFile, { force: true });
}
process.exit(failures.length ? 1 : 0);
