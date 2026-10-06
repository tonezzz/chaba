#!/usr/bin/env node
"use strict";
// gev-cast-verify — the verify-after-act check for GEV screen casts.
//
// A cast tool returning ok is NOT evidence the screen shows the page.
// This script casts /apps/gev/ to a real connected vcast display and then
// reads back state from BOTH ground truths before calling it done:
//
//   1. relay registry  GET <api>/displays  -> state=nav, state_detail
//      carries the GEV url + "p0:frame-ok" (the iframe's own onload —
//      render proof, not just delivery)
//   2. gev-gemini cmd relay  GET <gev-cmd>/command/health -> the page
//      registered a passive remote keyed {screen, pane}
//   3. snapshot path  snap-request -> GET /frame -> nav-mode iframes are
//      expected to answer error:"uncapturable-iframe"; the detail field
//      then carries the live iframe src (with screen/pane params), which
//      is itself the evidence. A JPEG frame also passes.
//
// Then it exercises the displaced-content contract (ada-pi feafff7): a
// camwall nav over-writing the GEV pane must remove the GEV remote and
// flip the display state — that state read is what cast_to_screen turns
// into a "displaced" note + split/PiP suggestion. The suggested
// remediation is exercised too: layout {panes:2, mode:pip} + per-pane
// nav puts GEV and camwall side by side.
//
// SW stale-cache case: fetches /apps/sw.js and asserts the apps-* purge
// shipped (2026-10-04 incident: apps-v6 cached pages with query strings
// stripped so ?v=N never busted), and that /apps/vcast/sw.js keeps its
// cache inside the vcast-* namespace the purge leaves alone. Deployed vs
// repo drift on either file is a WARN (deploys lag intentionally), not a
// FAIL — but the purge absent entirely is a FAIL.
//
// Usage:
//   node gev-cast-verify.mjs [--screen 6] [--api <url>] [--gev-cmd <url>]
//                            [--gev-url <url>] [--wall-url <url>]
//                            [--repo <path-to-repo>] [--no-restore]
//
// Env equivalents: VCAST_SCREEN VCAST_API GEV_CMD GEV_URL WALL_URL
// Defaults target the live tailnet deployment and lab screen 6
// (vcast-real@idc02). Needs a CONNECTED display on the target screen —
// headless sims that don't render iframes will fail frame-ok honestly.
//
// Exits 0 on pass, 1 on any FAIL.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const arg = (name, dflt) => {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : dflt;
};
const SCREEN = parseInt(
  arg("screen", process.env.VCAST_SCREEN || "6"), 10);
const API = (arg("api", process.env.VCAST_API ||
  "https://tony-dell.taila0626a.ts.net/api/input-bridge")).replace(/\/+$/, "");
const GEV_CMD = (arg("gev-cmd", process.env.GEV_CMD ||
  "https://tony-dell.taila0626a.ts.net/apps/gev-cmd")).replace(/\/+$/, "");
const ORIGIN = new URL(API).origin;
const GEV_URL = arg("gev-url", process.env.GEV_URL || `${ORIGIN}/apps/gev/`);
const WALL_URL = arg("wall-url", process.env.WALL_URL || `${ORIGIN}/apps/camwall/`);
// --repo = path to the deployed-statics dir for the drift WARN
// (default: this repo's stacks/web/public/apps)
const APPS_DIR = arg("repo", process.env.REPO ||
  path.resolve(HERE, "../public/apps"));
const RESTORE = !process.argv.includes("--no-restore");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const failures = [];
function check(name, cond, detail = "") {
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
  if (!cond) failures.push(name);
}
function warn(name, detail = "") {
  console.log(`WARN  ${name}${detail ? `  (${detail})` : ""}`);
}

const api = async (p) =>
  (await fetch(`${API}${p}`)).json().catch(() => ({}));
const post = async (p, body) => {
  const r = await fetch(`${API}${p}`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return { status: r.status, data: await r.json().catch(() => ({})) };
};
const screenState = async () => {
  const d = await api("/displays");
  return (d.screens || []).find((s) => s.screen === SCREEN) || null;
};
const gevHealth = async () =>
  (await fetch(`${GEV_CMD}/command/health`)).json().catch(() => ({}));
const gevRemote = async () => {
  const h = await gevHealth();
  return (h.remotes || []).find((r) => r.screen === SCREEN) || null;
};
const pub = (msg) => post("/pub", { screen: SCREEN, msg });

async function poll(ms, fn, step = 2000) {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    const v = await fn();
    if (v) return v;
    await sleep(step);
  }
  return null;
}
const stateIs = (s, want) =>
  s && s.state === "nav" && (s.state_detail || "").includes(want);
const frameOk = (s, pane) =>
  (s.state_detail || "").includes(`p${pane}:frame-ok`);

// ---------------------------------------------------------------------------
console.log(`gev-cast-verify  screen=${SCREEN}  api=${API}`);

// --- target screen must exist and be connected -------------------------------
const target = await screenState();
check("target screen registered", !!target,
  target ? `${target.name}/${target.label}` : "not in /displays");
check("target screen connected", !!(target && target.connected),
  "a state read requires a live display socket");
if (!target || !target.connected) {
  console.log("aborting — no live display to verify against");
  process.exit(1);
}

// --- shared /apps/sw.js self-heal purge (apps-v6 stale-cache case) -----------
{
  const sw = await (await fetch(`${ORIGIN}/apps/sw.js`)).text();
  check("/apps/sw.js purges apps-* caches on activate",
    /caches\.keys/.test(sw) && /apps-/.test(sw) && /caches\.delete/.test(sw),
    "2026-10-04 stale-cache self-heal");
  check("/apps/sw.js does not itself cache (no fetch listener)",
    !/addEventListener\(\s*['"`]fetch['"`]/.test(sw),
    "a bare respondWith(fetch()) adds Safari noise");
  const repoSw = path.join(APPS_DIR, "sw.js");
  try {
    if (fs.readFileSync(repoSw, "utf8") !== sw)
      warn("/apps/sw.js differs from repo copy",
        "deployed worker drifted from stacks/web/public/apps/sw.js");
  } catch { /* repo file not found — skip drift check */ }
}
{
  const sw = await (await fetch(`${ORIGIN}/apps/vcast/sw.js`)).text();
  const m = sw.match(/CACHE_NAME\s*=\s*["'`]([\w.-]+)/);
  check("/apps/vcast/sw.js cache stays in vcast-* namespace",
    !!m && m[1].startsWith("vcast-"),
    m ? `CACHE_NAME=${m[1]} (purge leaves vcast-* alone)` : "no CACHE_NAME");
  const repoSw = path.join(APPS_DIR, "vcast/sw.js");
  try {
    if (fs.readFileSync(repoSw, "utf8") !== sw)
      warn("/apps/vcast/sw.js differs from repo copy",
        "deployed worker drifted — check for an unpulled deploy");
  } catch { /* skip */ }
}

// --- ACT: cast GEV ------------------------------------------------------------
await pub({ type: "nav", url: GEV_URL });

// --- VERIFY: state read, both ground truths ----------------------------------
const onGev = await poll(30000, async () => {
  const s = await screenState();
  return stateIs(s, "/apps/gev") && frameOk(s, 0) ? s : null;
});
check("state read: screen shows GEV (nav + p0:frame-ok)", !!onGev,
  onGev ? onGev.state_detail : "timeout — last: " +
    JSON.stringify(await screenState()));

const remote = await poll(15000, async () => await gevRemote());
check("gev-cmd remote registered for screen", !!remote,
  remote ? JSON.stringify(remote) : "no remote on screen " + SCREEN);

// snapshot: nav-mode iframes answer uncapturable-iframe — the contract is
// that the error's detail carries the real iframe src (still evidence)
const token = `gevverify-${Date.now()}`;
await pub({ type: "snap-request", token });
const frame = await poll(10000, async () => {
  const r = await fetch(`${API}/frame?screen=${SCREEN}&token=${token}`);
  const ct = r.headers.get("content-type") || "";
  if (ct.startsWith("image/")) return { img: true };
  const j = await r.json().catch(() => ({}));
  // "frame not ready" is the pre-answer state — keep polling
  return j.error && j.error !== "frame not ready" ? j : null;
}, 1000);
check("snapshot read answered (frame or uncapturable-iframe)", !!frame);
if (frame && !frame.img) {
  check("uncapturable-iframe detail carries the live GEV iframe src",
    frame.error === "uncapturable-iframe" &&
      (frame.detail || "").includes("/apps/gev"),
    `${frame.error} :: ${String(frame.detail || "").slice(0, 120)}`);
}

// --- DISPLACE: camwall nav over-writes the GEV pane ---------------------------
await pub({ type: "nav", url: WALL_URL });
const onWall = await poll(30000, async () => {
  const s = await screenState();
  return stateIs(s, "/apps/camwall") && frameOk(s, 0) ? s : null;
});
check("displaced: state read shows camwall, not GEV", !!onWall,
  onWall ? onWall.state_detail : "timeout");

const displaced = await poll(15000, async () =>
  (await gevRemote()) ? null : true);
check("displaced: GEV remote gone after overwrite", !!displaced,
  "ada-pi feafff7 turns this read into the displaced note + split/PiP hint");

// --- REMEDIATE: the suggested split/PiP layout --------------------------------
await pub({ type: "layout", panes: 2, mode: "pip" });
await pub({ type: "nav", pane: 1, url: WALL_URL });
await pub({ type: "nav", pane: 0, url: GEV_URL });
const onSplit = await poll(45000, async () => {
  const s = await screenState();
  return s && s.panes === 2 && frameOk(s, 0) && frameOk(s, 1) ? s : null;
});
check("remediation: pip split renders both panes", !!onSplit,
  onSplit ? `${onSplit.state_detail} (panes=${onSplit.panes})` : "timeout");
const remote2 = await poll(15000, async () => await gevRemote());
check("remediation: GEV remote back on pane 0",
  !!remote2 && (remote2.pane ?? 0) === 0, JSON.stringify(remote2));

// --- restore the screen to idle ----------------------------------------------
if (RESTORE) {
  await pub({ type: "stop" });
  const idle = await poll(10000, async () => {
    const s = await screenState();
    return s && s.state === "idle" ? s : null;
  });
  check("restore: screen back to idle", !!idle);
} else {
  console.log("note: --no-restore, leaving the split cast up");
}

console.log(failures.length
  ? `\n${failures.length} FAIL: ${failures.join(", ")}`
  : "\nall checks passed");
process.exit(failures.length ? 1 : 0);
