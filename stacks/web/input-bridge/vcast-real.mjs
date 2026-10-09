#!/usr/bin/env node
"use strict";
// vcast-real — a REAL-browser vcast display client. Unlike vcast-headless
// (a node sim that only acks messages), this drives an actual headless
// Chromium to the real vcast page, so layouts, iframes, camera frames and
// the GEV remote-client all genuinely render — scenario assertions like
// gev_view_near and pN:frame-ok then verify real state, not sim state.
//
// Flow mirrors the headless client:
//   1. open the page (it connects ws + register-display -> pending)
//   2. poll /displays for our pending sid (identified by ?label=)
//   3. POST /claim {sid, name: screen-N, admin_key}
//   4. stay attached; on page crash, relaunch and re-claim
//
//   ADA_ADMIN_KEY=... VCAST_NAME=screen-6 node vcast-real.mjs
//
// Env:
//   VCAST_PAGE  vcast page URL (default live tony-dell)
//   VCAST_API   input-bridge HTTP base (default via tony-dell Caddy)
//   VCAST_LABEL display label announced via ?label= (default vcast-real)
//   VCAST_NAME  claim name, e.g. screen-6 (default unset -> auto slot)
//   VCAST_DEV_ID stable device_id seeded into the page's localStorage —
//               dedupes pending rows across browser relaunches
//   VCAST_KEY_FILE persist the minted api_key here — a relaunched browser
//               re-registers with the old key instead of re-minting
//               through /claim. Without it every relaunch goes
//               pending->claim, which is how the 2026-10-09 drift loop
//               stacked dead screen-N entries (1,6,8,9 for one client).
//   ADA_ADMIN_KEY  admin key for /claim

import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const PAGE = process.env.VCAST_PAGE
  || "https://tony-dell.taila0626a.ts.net/apps/vcast/index.html";
const API = (process.env.VCAST_API
  || "https://tony-dell.taila0626a.ts.net/api/input-bridge").replace(/\/+$/, "");
const LABEL = process.env.VCAST_LABEL || "vcast-real";
const NAME = process.env.VCAST_NAME || "";
const DEV_ID = process.env.VCAST_DEV_ID || "";
const ADMIN = process.env.ADA_ADMIN_KEY || "";
const KEY_FILE = process.env.VCAST_KEY_FILE || "";
const CLAIM_WAIT_MS = 120_000;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let persistedKey = "";
if (KEY_FILE) {
  try {
    persistedKey = fs.readFileSync(KEY_FILE, "utf8").trim();
    if (persistedKey) console.log("[key] loaded persisted api_key from", KEY_FILE);
  } catch { /* first boot */ }
}
function saveKey(k) {
  if (!KEY_FILE || !k || k === persistedKey) { persistedKey = k || persistedKey; return; }
  persistedKey = k;
  try {
    fs.mkdirSync(path.dirname(KEY_FILE), { recursive: true });
    fs.writeFileSync(KEY_FILE, k + "\n", { mode: 0o600 });
  } catch (e) { console.log("[key] save failed:", e.message); }
}

async function pollDisplays() {
  try {
    const d = await (await fetch(`${API}/displays`)).json();
    return {
      sid: (d.pending || []).find((p) => p.label === LABEL)?.sid || null,
      // a connected entry with our label means the page self-registered
      // with a persisted key — no pending/claim cycle needed
      live: (d.screens || []).find((s) => s.label === LABEL && s.connected) || null,
    };
  } catch { return { sid: null, live: null }; }
}

async function claim() {
  const deadline = Date.now() + CLAIM_WAIT_MS;
  let forced = false;
  while (Date.now() < deadline) {
    const { sid, live } = await pollDisplays();
    // persisted-key path: the page already holds a valid key and
    // registered itself — waiting on a pending sid that never comes
    // would burn the whole CLAIM_WAIT_MS then relaunch a healthy page
    // (the pre-keyfile loop that kept re-claiming screen-N slots)
    if (live) return true;
    if (sid) {
      const r = await fetch(`${API}/claim`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          sid, name: NAME || LABEL, admin_key: ADMIN,
          force: forced || undefined,
        }),
      });
      const j = await r.json().catch(() => ({}));
      console.log("[claim]", JSON.stringify({ status: r.status, ...j }));
      // 409 = a stale ada key still pins the screen-N name — revoke and
      // re-mint once (same failure that parked vcast-headless on 409s)
      if (r.status === 409 && !forced) { forced = true; continue; }
      return r.ok;
    }
    await sleep(2000);
  }
  return false;
}

async function run() {
  for (;;) {
    let browser;
    try {
      browser = await chromium.launch({
        headless: true,
        args: [
          "--no-sandbox",
          "--enable-unsafe-swiftshader",       // Cesium/WebGL w/o GPU
          "--use-angle=swiftshader",
          "--autoplay-policy=no-user-gesture-required",
          "--mute-audio",
        ],
      });
      browser.on("disconnected", () =>
        console.log("[down] browser disconnected"));
      const ctx = await browser.newContext({
        viewport: { width: 1280, height: 720 },
        userAgent: "vcast-real/1.0 (headless-chromium)",
      });
      // seed identity before page scripts run — the fresh browser profile
      // would otherwise mint a new device_id (duplicate pending rows) and
      // lose the api_key (full re-claim on every relaunch)
      if (persistedKey || DEV_ID) {
        await ctx.addInitScript(([k, d]) => {
          try {
            if (k && !localStorage.getItem("vcast.api_key"))
              localStorage.setItem("vcast.api_key", k);
            if (d && !localStorage.getItem("vcast.device_id"))
              localStorage.setItem("vcast.device_id", d);
          } catch (e) {}
        }, [persistedKey, DEV_ID]);
      }
      const page = await ctx.newPage();
      page.on("pageerror", (e) => console.log("[pageerror]", String(e).slice(0, 200)));
      page.on("crash", () => console.log("[down] page CRASHED (renderer died — OOM or GPU kill)"));
      page.on("console", (m) => {
        if (m.type() === "error") console.log("[console]", m.text().slice(0, 160));
      });
      const url = `${PAGE}?label=${encodeURIComponent(LABEL)}`;
      console.log("[open]", url);
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
      const tClaim = Date.now();
      const ok = await claim();
      if (!ok) {
        // don't hold a pending page forever — relaunch and re-claim
        // (a 409 stale-key pin once parked the display silently)
        console.log("[warn] claim timed out — relaunching");
        continue;   // finally closes the browser; loop re-opens + re-claims
      }
      // the page may have minted a fresh key via /claim — persist it
      try {
        const k = await page.evaluate(() =>
          localStorage.getItem("vcast.api_key"));
        if (k) saveKey(k);
      } catch (e) {}
      console.log(`[ready] claimed attach_ms=${Date.now() - tClaim}`);
      // a renderer crash doesn't fire the page "close" event — the ws
      // dies but waitForEvent would hang forever on a wedged page.
      // Probe the renderer every 30s; a dead one gets closed so the
      // relaunch loop actually runs (suspected cause of the real-6
      // 1-3min drop cycle: GEV/Cesium under swiftshader OOMing the tab).
      const aliveT = setInterval(async () => {
        try { await page.evaluate("1"); }
        catch (e) {
          console.log("[down] renderer unresponsive — forcing relaunch");
          try { await page.close(); } catch (e2) {}
        }
      }, 30000);
      // stay attached until the page dies; any disconnect -> relaunch loop
      await page.waitForEvent("close", { timeout: 0 }).catch(() => {});
      clearInterval(aliveT);
      console.log("[down] page closed — relaunching in 5s");
    } catch (e) {
      console.log("[error]", String(e).slice(0, 200));
    } finally {
      try { await browser?.close(); } catch {}
      await sleep(5000);
    }
  }
}

run();
