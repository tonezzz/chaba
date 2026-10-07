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
//   ADA_ADMIN_KEY  admin key for /claim

import { chromium } from "playwright";

const PAGE = process.env.VCAST_PAGE
  || "https://tony-dell.taila0626a.ts.net/apps/vcast/index.html";
const API = (process.env.VCAST_API
  || "https://tony-dell.taila0626a.ts.net/api/input-bridge").replace(/\/+$/, "");
const LABEL = process.env.VCAST_LABEL || "vcast-real";
const NAME = process.env.VCAST_NAME || "";
const ADMIN = process.env.ADA_ADMIN_KEY || "";
const CLAIM_WAIT_MS = 120_000;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function findPendingSid() {
  try {
    const d = await (await fetch(`${API}/displays`)).json();
    const me = (d.pending || []).find((p) => p.label === LABEL);
    return me?.sid || null;
  } catch { return null; }
}

async function claim() {
  const deadline = Date.now() + CLAIM_WAIT_MS;
  let forced = false;
  while (Date.now() < deadline) {
    const sid = await findPendingSid();
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
      const ctx = await browser.newContext({
        viewport: { width: 1280, height: 720 },
        userAgent: "vcast-real/1.0 (headless-chromium)",
      });
      const page = await ctx.newPage();
      page.on("pageerror", (e) => console.log("[pageerror]", String(e).slice(0, 200)));
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
      console.log(`[ready] claimed attach_ms=${Date.now() - tClaim}`);
      // stay attached until the page dies; any disconnect -> relaunch loop
      await page.waitForEvent("close", { timeout: 0 }).catch(() => {});
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
