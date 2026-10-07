#!/usr/bin/env node
"use strict";
// vcast-headless — a headless vcast display for testing. Connects to the
// relay, goes through the real pending -> claim -> paired -> registered
// flow (POST /claim with ADA_ADMIN_KEY), then logs every message it
// receives on its vcast-N room. Run on idc03 (the relay host) during
// scenario tests — loopback defaults below assume that.
//
//   ADA_ADMIN_KEY=... node vcast-headless.mjs [ws-url] [api-base]
//
// Ctrl-C releases the screen (POST /release) so the number frees up.
//
// VCAST_NAME   screen name claimed via /claim (default screen-1)
// VCAST_LABEL  display label shown in /displays (default headless-test)
// VCAST_DEV_ID stable device_id so reconnects reuse the pending slot
// VCAST_KEY_FILE  persist the minted api_key here — a restart re-registers
//              with the old key (one ada auth hop, well under the <5s
//              attach budget) instead of re-minting through /claim.
//
// Claim retry contract (added 2026-10-07 — headless@2/@4 sat dead for two
// days after the idc01->idc03 relay move because the pre-migration ada
// keys still pinned screen-2/screen-4): a 409 answer means a stale key
// holds the name, so retry once with force=true (revoke+re-mint). Other
// failures retry on a 30s-capped backoff forever — a dead display that
// goes quiet is the failure mode this file exists to prevent.

const WS_URL = process.argv[2] || "ws://127.0.0.1:3010/ws";
const API = (process.argv[3] || "http://127.0.0.1:3010").replace(/\/+$/, "");
const ADMIN_KEY = process.env.ADA_ADMIN_KEY || ""; // optional — relay env key is preferred
const LABEL = process.env.VCAST_LABEL || "headless-test";
const DEV_ID = process.env.VCAST_DEV_ID || "";
const CLAIM_NAME = process.env.VCAST_NAME || "screen-1";
const KEY_FILE = process.env.VCAST_KEY_FILE || "";

import fs from "node:fs";
import path from "node:path";
import WebSocket from "ws";

let ws, screen = null, apiKey = null, panes = 1;
let lastState = "idle", lastDetail = "";
let connectAt = Date.now();

if (KEY_FILE) {
  try {
    apiKey = fs.readFileSync(KEY_FILE, "utf8").trim() || null;
    if (apiKey) console.log("[key] loaded persisted api_key from", KEY_FILE);
  } catch { /* first boot */ }
}
function saveKey() {
  if (!KEY_FILE || !apiKey) return;
  try {
    fs.mkdirSync(path.dirname(KEY_FILE), { recursive: true });
    fs.writeFileSync(KEY_FILE, apiKey + "\n", { mode: 0o600 });
  } catch (e) { console.log("[key] save failed:", e.message); }
}

// Re-register drives the pending->claim cycle; claim retries the same sid
// on transient failures and force-claims once on a 409 name-pin.
async function claim(sid, force = false, attempt = 1) {
  let status = 0, txt = "";
  try {
    const r = await fetch(`${API}/claim`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        sid, admin_key: ADMIN_KEY || undefined, name: CLAIM_NAME,
        force: force || undefined,
      }),
    });
    status = r.status;
    txt = await r.text();
  } catch (e) {
    txt = e.message;
  }
  console.log("[claim]", status || "err", txt);
  if (status === 200) return;
  if (status === 409 && !force) return claim(sid, true, attempt);
  if (status === 404) {          // pending sid expired — re-register
    try {
      ws.send(JSON.stringify({
        type: "register-display", api_key: "", label: LABEL, device_id: DEV_ID,
      }));
    } catch {}
    return;
  }
  // bounded fast retries then a steady 30s cadence — self-heals when ada
  // or the relay recovers without hot-looping
  setTimeout(() => claim(sid, force, attempt + 1),
    Math.min(30000, 1500 * attempt));
}

function connect() {
  connectAt = Date.now();
  ws = new WebSocket(WS_URL);
  ws.on("open", () => {
    ws.send(JSON.stringify({ type: "register-display", api_key: apiKey || "", label: LABEL, device_id: DEV_ID }));
  });
  ws.on("message", async (raw) => {
    let m;
    try { m = JSON.parse(raw.toString()); } catch (e) { return; }
    if (m.type === "ping" || m.type === "presence") return;
    console.log("[recv]", JSON.stringify({ ...m, api_key: m.api_key ? "***" : undefined }));
    if (m.type === "pending") claim(m.sid);
    if (m.type === "paired") {
      apiKey = m.api_key;
      saveKey();
      ws.send(JSON.stringify({ type: "register-display", api_key: apiKey, label: LABEL }));
    }
    if (m.type === "registered") {
      screen = m.screen;
      console.log(`[registered] Screen #${screen} (${m.name}) attach_ms=${Date.now() - connectAt}`);
    }
    if (m.type === "unpaired") {
      apiKey = null; screen = null;
      if (KEY_FILE) try { fs.rmSync(KEY_FILE, { force: true }); } catch {}
      // re-enter the pending flow so a release self-heals without
      // waiting for a ws drop
      ws.send(JSON.stringify({ type: "register-display", api_key: "", label: LABEL, device_id: DEV_ID }));
    }
    // Track pane/zoom state like the real page: layout sets the grid,
    // zoom focuses one pane, unzoom/stop reset. The relay derives the
    // pane count from a leading integer in state detail on "layout".
    if (m.type === "layout" && m.panes) panes = Math.max(1, +m.panes || 1);
    if (m.type === "stop") panes = 1;
    if (m.type === "gesture") {
      // a real page would open the camera; the sim just acks state
      lastState = m.mode === "off" ? "idle" : `gesture-${m.mode}`;
      lastDetail = m.mode === "off" ? "" : `gesture:${m.mode}`;
      ws.send(JSON.stringify({ type: "state", state: lastState, detail: lastDetail }));
    }
    if (m.type === "snap-request" && screen != null) {
      // No real pixels — report honestly instead of letting the tool poll
      // itself into "did not return a frame — offline or stuck" (the sim
      // is neither). The bridge forwards error+state in the frame body.
      try {
        await fetch(`${API}/frame`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            screen, token: m.token || "", state: lastState,
            detail: lastDetail, error: "simulated",
          }),
        });
      } catch {}
    }
    if (["play", "image", "nav", "audio", "stop", "layout", "zoom", "unzoom"].includes(m.type)) {
      lastState = m.type === "stop" ? "idle" : m.type;
      lastDetail = m.type === "layout" ? `${panes}panes` : (m.url || "");
      ws.send(JSON.stringify({ type: "state", state: lastState, detail: lastDetail }));
    }
  });
  ws.on("close", () => setTimeout(connect, 2000));
  ws.on("error", (e) => console.error("[ws]", e.message));
}

async function release() {
  if (screen == null || !ADMIN_KEY) process.exit(0);
  try {
    await fetch(`${API}/release`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ screen, admin_key: ADMIN_KEY }),
    });
  } catch {}
  process.exit(0);
}
process.on("SIGINT", release);
process.on("SIGTERM", release);

console.log(`[vcast-headless] ws=${WS_URL} api=${API} label=${LABEL} claim=${!!ADMIN_KEY} keyfile=${KEY_FILE || "off"}`);
connect();
