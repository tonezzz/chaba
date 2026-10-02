// wall-render-check — render-layer smoke test for cam-wall pages.
//
// The 2026-10-02 'div is not defined' outage: manifests and thumbs were
// perfect, but the page JS crashed building the grid — every layer of
// verification we had checked DATA, none rendered the DOM. This loads
// each enabled wall headless and asserts what the user actually sees:
//   1. .cell count == manifest cam count
//   2. every cell <img> got a non-empty src
//   3. no pageerror fired
// On failure POSTs /api/notify so Ada relays it. Run on a timer (idc02
// has the playwright image via vcast-real@).
//
//   node wall-render-check.mjs            # all enabled zones
//   node wall-render-check.mjs --zone X   # single zone

import { chromium } from "playwright";

const BRIDGE = process.env.VCAST_API ||
  "https://tony-dell.taila0626a.ts.net/api/input-bridge";
const WALL = process.env.WALL_BASE ||
  "https://tony-dell.taila0626a.ts.net/apps/camwall";
const NOTIFY = process.env.ADA_NOTIFY_URL ||
  "https://idc01.taila0626a.ts.net/api/notify";
const NOTIFY_KEY = process.env.ADA_NOTIFY_KEY || process.env.ADA_API_KEY || "";
const ONLY = process.argv.includes("--zone")
  ? process.argv[process.argv.indexOf("--zone") + 1] : null;

async function enabledZones() {
  const r = await fetch(`${BRIDGE}/camwall`);
  const d = await r.json();
  return Object.entries(d.zones || {})
    .filter(([, v]) => v.enabled)
    .map(([k]) => k);
}

async function notify(text) {
  if (!NOTIFY_KEY) { console.log("notify skipped (no key):", text); return; }
  await fetch(NOTIFY, {
    method: "POST",
    headers: { "content-type": "application/json", "x-api-key": NOTIFY_KEY },
    body: JSON.stringify({ text: text.slice(0, 400), urgent: "0" }),
  }).catch(e => console.error("notify failed:", e.message));
}

const zones = ONLY ? [ONLY] : await enabledZones();
const fails = [];

const b = await chromium.launch();
for (const zone of zones) {
  const pg = await b.newPage();
  const errs = [];
  pg.on("pageerror", e => errs.push(e.message.slice(0, 120)));
  try {
    await pg.goto(`${WALL}/?zone=${zone}`,
      { waitUntil: "networkidle", timeout: 45000 });
    await pg.waitForTimeout(6000);
    const info = await pg.evaluate(() => ({
      cells: document.querySelectorAll(".cell").length,
      imgsEmpty: [...document.querySelectorAll(".cell img")]
        .filter(i => !i.src).length,
      imgsBroken: [...document.querySelectorAll(".cell img")]
        .filter(i => i.src && i.complete && i.naturalWidth === 0).length,
      hud: document.getElementById("hud")?.textContent || "",
      jserrShown: document.getElementById("jserr")?.style.display === "block",
    }));
    // cell count must match the manifest the hud claims
    const m = info.hud.match(/(\d+)\/(\d+) live/);
    const expected = m ? +m[2] : null;
    const bad = [];
    if (errs.length) bad.push(`pageerror: ${errs[0]}`);
    if (expected != null && info.cells !== expected)
      bad.push(`${info.cells} cells for ${expected} cams`);
    if (info.imgsEmpty) bad.push(`${info.imgsEmpty} imgs with empty src`);
    if (info.imgsBroken) bad.push(`${info.imgsBroken} broken imgs`);
    if (bad.length) {
      fails.push(`${zone}: ${bad.join("; ")}`);
      console.log(`FAIL ${zone} — ${bad.join("; ")}`);
    } else {
      console.log(`ok   ${zone} — ${info.cells} cells (${info.hud})`);
    }
  } catch (e) {
    fails.push(`${zone}: load failed ${e.message.slice(0, 120)}`);
    console.log(`FAIL ${zone} — ${e.message.slice(0, 120)}`);
  }
  await pg.close();
}
await b.close();

if (fails.length) {
  await notify(`camwall render check FAILED — ${fails.join(" | ")}`);
  process.exit(1);
}
console.log("all walls render clean");
