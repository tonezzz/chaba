#!/usr/bin/env node
"use strict";
// vcast-headless — a headless vcast display for testing. Connects to the
// relay, goes through the real pending -> claim -> paired -> registered
// flow (POST /claim with ADA_ADMIN_KEY), then logs every message it
// receives on its vcast-N room. Run on idc01 (the relay host) during
// scenario tests — loopback defaults below assume that.
//
//   ADA_ADMIN_KEY=... node vcast-headless.mjs [ws-url] [api-base]
//
// Ctrl-C releases the screen (POST /release) so the number frees up.
//
// VCAST_NAME   screen name claimed via /claim (default screen-1)
// VCAST_LABEL  display label shown in /displays (default headless-test)
// VCAST_DEV_ID stable device_id so reconnects reuse the pending slot

const WS_URL = process.argv[2] || "ws://127.0.0.1:3010/ws";
const API = (process.argv[3] || "http://127.0.0.1:3010").replace(/\/+$/, "");
const ADMIN_KEY = process.env.ADA_ADMIN_KEY || ""; // optional — relay env key is preferred
const LABEL = process.env.VCAST_LABEL || "headless-test";
const DEV_ID = process.env.VCAST_DEV_ID || "";
const CLAIM_NAME = process.env.VCAST_NAME || "screen-1";

import WebSocket from "ws";

let ws, screen = null, apiKey = null, panes = 1;

function connect() {
  ws = new WebSocket(WS_URL);
  ws.on("open", () => {
    ws.send(JSON.stringify({ type: "register-display", api_key: apiKey || "", label: LABEL, device_id: DEV_ID }));
  });
  ws.on("message", async (raw) => {
    let m;
    try { m = JSON.parse(raw.toString()); } catch (e) { return; }
    if (m.type === "ping" || m.type === "presence") return;
    console.log("[recv]", JSON.stringify({ ...m, api_key: m.api_key ? "***" : undefined }));
    if (m.type === "pending") {
      const r = await fetch(`${API}/claim`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ sid: m.sid, admin_key: ADMIN_KEY || undefined, name: CLAIM_NAME }),
      });
      console.log("[claim]", r.status, await r.text());
    }
    if (m.type === "paired") {
      apiKey = m.api_key;
      ws.send(JSON.stringify({ type: "register-display", api_key: apiKey, label: LABEL }));
    }
    if (m.type === "registered") {
      screen = m.screen;
      console.log(`[registered] Screen #${screen} (${m.name}) — receiving`);
    }
    if (m.type === "unpaired") {
      apiKey = null; screen = null;
      // re-enter the pending flow so a release self-heals without
      // waiting for a ws drop
      ws.send(JSON.stringify({ type: "register-display", api_key: "", label: LABEL, device_id: DEV_ID }));
    }
    // Track pane/zoom state like the real page: layout sets the grid,
    // zoom focuses one pane, unzoom/stop reset. The relay derives the
    // pane count from a leading integer in state detail on "layout".
    if (m.type === "layout" && m.panes) panes = Math.max(1, +m.panes || 1);
    if (m.type === "stop") panes = 1;
    if (["play", "image", "nav", "audio", "stop", "layout", "zoom", "unzoom"].includes(m.type)) {
      const st = m.type === "stop" ? "idle" : m.type;
      const detail = m.type === "layout" ? `${panes}panes` : (m.url || "");
      ws.send(JSON.stringify({ type: "state", state: st, detail }));
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

console.log(`[vcast-headless] ws=${WS_URL} api=${API} label=${LABEL} claim=${!!ADMIN_KEY}`);
connect();
