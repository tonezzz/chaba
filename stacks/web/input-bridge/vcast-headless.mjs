#!/usr/bin/env node
"use strict";
// vcast-headless — a headless vcast display for testing. Connects to the
// relay, goes through the real pending -> claim -> paired -> registered
// flow (POST /claim with ADA_ADMIN_KEY), then logs every message it
// receives on its vcast-N room. Run on tony-dell during scenario tests.
//
//   ADA_ADMIN_KEY=... node vcast-headless.mjs [ws-url] [api-base]
//
// Ctrl-C releases the screen (POST /release) so the number frees up.

const WS_URL = process.argv[2] || "ws://127.0.0.1:3010/ws";
const API = (process.argv[3] || "http://127.0.0.1:3010").replace(/\/+$/, "");
const ADMIN_KEY = process.env.ADA_ADMIN_KEY || "";
const LABEL = process.env.VCAST_LABEL || "headless-test";

import WebSocket from "ws";

let ws, screen = null, apiKey = null;

function connect() {
  ws = new WebSocket(WS_URL);
  ws.on("open", () => {
    ws.send(JSON.stringify({ type: "register-display", api_key: apiKey || "", label: LABEL }));
  });
  ws.on("message", async (raw) => {
    let m;
    try { m = JSON.parse(raw.toString()); } catch (e) { return; }
    if (m.type === "ping" || m.type === "presence") return;
    console.log("[recv]", JSON.stringify({ ...m, api_key: m.api_key ? "***" : undefined }));
    if (m.type === "pending" && ADMIN_KEY) {
      const r = await fetch(`${API}/claim`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ sid: m.sid, admin_key: ADMIN_KEY, name: "screen-1" }),
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
    if (m.type === "unpaired") { apiKey = null; screen = null; }
    if (["play", "image", "nav", "audio", "stop"].includes(m.type)) {
      ws.send(JSON.stringify({ type: "state", state: m.type === "stop" ? "idle" : m.type, detail: m.url || "" }));
    }
  });
  ws.on("close", () => setTimeout(connect, 2000));
  ws.on("error", (e) => console.error("[ws]", e.message));
}

async function release() {
  if (screen == null || !ADMIN_KEY) process.exit(0);
  try {
    const r = await fetch(`${API}/release`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ screen, admin_key: ADMIN_KEY }),
    });
    console.log("[release]", r.status, await r.text());
  } catch (e) { console.error("[release]", e.message); }
  process.exit(0);
}
process.on("SIGINT", release);
process.on("SIGTERM", release);

connect();
console.log(`[vcast-headless] ws=${WS_URL} api=${API} label=${LABEL} claim=${!!ADMIN_KEY}`);
