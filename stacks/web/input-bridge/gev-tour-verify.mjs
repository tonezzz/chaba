#!/usr/bin/env node
"use strict";
// gev-tour-verify — play a GEV tour end-to-end on a real (or already-casted)
// page and prove the checkpoint contract: stops are reported reached strictly
// in order, then the tour ends done.
//
// Ground truths, two independent channels:
//   1. tour_status polling  POST /apps/gev-cmd/command {name:'tour_status',
//      screen, wait:8} — the page answers with its ordered checkpoints[].
//      Works against the CURRENT deployed bridge (no rebuild needed).
//   2. tour_event stream    GET /apps/gev-cmd/command/events?since=N — the
//      bridge-side log of frames the page emits per leg/checkpoint/end.
//      WARN (not FAIL) when the endpoint 404s — bridge predates the change.
//
// Usage:
//   node gev-tour-verify.mjs [--screen 6] [--tour london-icons]
//     [--api <url>] [--gev-cmd <url>] [--gev-url <url>]
//     [--no-cast] [--no-restore] [--timeout-s <n>]
//
// --no-cast assumes a GEV remote is already up on --screen.
// Exits 0 on pass, 1 on any FAIL.

import { fileURLToPath } from "node:url";
import path from "node:path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const arg = (name, dflt) => {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : dflt;
};
const SCREEN = parseInt(arg("screen", process.env.VCAST_SCREEN || "6"), 10);
const TOUR = arg("tour", process.env.GEV_TOUR || "london-icons");
const API = (arg("api", process.env.VCAST_API ||
  "https://tony-dell.taila0626a.ts.net/api/input-bridge")).replace(/\/+$/, "");
const GEV_CMD = (arg("gev-cmd", process.env.GEV_CMD ||
  "https://tony-dell.taila0626a.ts.net/apps/gev-cmd")).replace(/\/+$/, "");
const ORIGIN = new URL(API).origin;
const GEV_URL = arg("gev-url", process.env.GEV_URL || `${ORIGIN}/apps/gev/`);
const CAST = !process.argv.includes("--no-cast");
const RESTORE = !process.argv.includes("--no-restore");
const TIMEOUT_S = parseInt(arg("timeout-s", "0"), 10); // 0 = derive from tour

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
const pub = (msg) =>
  fetch(`${API}/pub`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ screen: SCREEN, msg }),
  }).then((r) => r.json()).catch(() => ({}));
const gevCmd = async (name, args = {}, wait = 8) => {
  const r = await fetch(`${GEV_CMD}/command`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ name, args, screen: SCREEN, wait }),
  }).catch(() => null);
  return r ? { status: r.status, data: await r.json().catch(() => ({})) }
           : { status: 0, data: {} };
};
const screenState = async () => {
  const d = await api("/displays");
  return (d.screens || []).find((s) => s.screen === SCREEN) || null;
};
const gevRemote = async () => {
  const h = await fetch(`${GEV_CMD}/command/health`).then((r) => r.json()).catch(() => ({}));
  return (h.remotes || []).find((r) => r.screen === SCREEN) || null;
};
async function poll(ms, fn, step = 1500) {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    const v = await fn();
    if (v) return v;
    await sleep(step);
  }
  return null;
}

// ---------------------------------------------------------------------------
console.log(`gev-tour-verify  screen=${SCREEN}  tour=${TOUR}  cmd=${GEV_CMD}`);

// --- fetch the tour definition: expected checkpoint ids + ETA bound --------
let tourDef = null;
{
  const url = `${ORIGIN}/apps/gev/tours/${TOUR}.json`;
  const r = await fetch(url).catch(() => null);
  check("tour definition reachable", !!r && r.ok, `${url} -> ${r && r.status}`);
  if (r && r.ok) tourDef = await r.json().catch(() => null);
  check("tour definition parses with ordered stops",
    !!tourDef && Array.isArray(tourDef.stops) && tourDef.stops.length > 0 &&
    tourDef.stops.every((s) => s.id),
    tourDef ? `${tourDef.stops.length} stops` : "no stops");
}
if (!tourDef) {
  console.log("aborting — cannot verify a tour whose definition won't load");
  process.exit(1);
}
const expectedIds = tourDef.stops.map((s) => s.id);
const etaS = tourDef.stops.reduce((a, s) =>
  a + (s.dwellS ?? tourDef.defaults?.dwellS ?? 6) +
      (s.camera?.durationS ?? tourDef.defaults?.durationS ?? 4), 0);
const limit = (TIMEOUT_S || Math.ceil(etaS * 2 + 45)) * 1000;

// --- target screen -----------------------------------------------------------
if (CAST) {
  const target = await screenState();
  check("target screen connected", !!(target && target.connected),
    target ? `${target.name}/${target.label}` : "not in /displays");
  if (!target || !target.connected) {
    console.log("aborting — no live display to verify against");
    process.exit(1);
  }
  await pub({ type: "nav", url: GEV_URL });
  const onGev = await poll(40000, async () => {
    const s = await screenState();
    return s && s.state === "nav" &&
      (s.state_detail || "").includes("/apps/gev") &&
      (s.state_detail || "").includes("p0:frame-ok") ? s : null;
  });
  check("cast: screen shows GEV (nav + p0:frame-ok)", !!onGev,
    onGev ? onGev.state_detail : "timeout");
}
const remote = await poll(20000, async () => await gevRemote());
check("gev-cmd remote registered for screen", !!remote,
  remote ? JSON.stringify(remote) : "no remote on screen " + SCREEN);
if (!remote) {
  console.log("aborting — nothing to drive");
  process.exit(1);
}
// the remote socket (and the tour player inside it) needs the app bundle
// booted — the runner only exists after init; give it a moment then start.
await sleep(8000);

// --- ACT: play the tour --------------------------------------------------------
const evSince = await (async () => {
  const r = await fetch(`${GEV_CMD}/command/events?since=0&limit=1`).catch(() => null);
  if (!r || r.status === 404) return -1; // old bridge — stream check is WARN-only
  const j = await r.json().catch(() => ({}));
  return j.last || 0;
})();
const started = await gevCmd("play_tour", { tour: TOUR }, 10);
const ack = (started.data.responses || []).map((r) => r.response || r)
  .find((r) => r && r.action === "play_tour");
check("play_tour acknowledged", !!ack && ack.ok === true,
  ack ? `stops=${ack.stops ?? ack.tour?.stops} etaS=${ack.etaS}` :
    JSON.stringify(started.data).slice(0, 160));

// --- VERIFY: poll tour_status; checkpoints must extend in order --------------
let last = [];
let finalState = null;
const deadline = Date.now() + limit;
while (Date.now() < deadline) {
  const st = await gevCmd("tour_status", {}, 8);
  const res = (st.data.responses || []).map((r) => r.response || r)
    .find((r) => r && Array.isArray(r.checkpoints));
  if (res) {
    const cps = res.checkpoints;
    // prefix-extension: every previously-seen checkpoint still at same index
    const prefixOk = last.every((c, i) =>
      cps[i] && cps[i].seq === c.seq && cps[i].id === c.id);
    if (!prefixOk) {
      check("checkpoints append-only and ordered", false,
        `order broke: had ${JSON.stringify(last.map((c) => c.id))} now ` +
        JSON.stringify(cps.map((c) => c.id)));
      break;
    }
    if (cps.length > last.length) {
      for (const c of cps.slice(last.length))
        console.log(`  checkpoint ${c.seq}: ${c.id} (arrived=${c.arrived})`);
      last = cps;
    }
    if (res.state === "done" || res.state === "stopped" || res.state === "error") {
      finalState = res;
      break;
    }
  }
  await sleep(1500);
}
check("checkpoints append-only and ordered", true,
  `${last.length} checkpoint(s) observed`);
check("tour reached terminal state", !!finalState,
  finalState ? finalState.state : `timeout after ${limit / 1000}s`);
check("tour ended done (not stopped/error)",
  !!finalState && finalState.state === "done",
  finalState ? `state=${finalState.state} err=${finalState.error || "-"}` : "");
check("all expected checkpoints reached in order",
  last.length === expectedIds.length &&
    last.every((c, i) => c.seq === i && c.id === expectedIds[i]),
  `got ${JSON.stringify(last.map((c) => c.id))} want ${JSON.stringify(expectedIds)}`);
const notArrived = last.filter((c) => c.arrived === false);
if (notArrived.length)
  warn("checkpoint(s) reported arrived=false",
    notArrived.map((c) => c.id).join(","));

// --- cross-check: bridge tour_event stream (if endpoint exists) ---------------
if (evSince < 0) {
  warn("bridge /command/events absent — stream check skipped",
    "deployed bridge predates tour_event logging; tour_status polling already proved order");
} else {
  const evs = await fetch(`${GEV_CMD}/command/events?since=${evSince}&limit=500`)
    .then((r) => r.json()).catch(() => ({}));
  const cps = (evs.events || []).filter((e) => e.kind === "checkpoint" && e.tour === TOUR);
  check("event stream: checkpoints in seq order",
    cps.length === expectedIds.length &&
      cps.every((e, i) => e.seq === i && e.id === expectedIds[i]),
    `streamed ${JSON.stringify(cps.map((e) => `${e.seq}:${e.id}`))}`);
  const end = (evs.events || []).find((e) => e.kind === "tour_end" && e.tour === TOUR);
  check("event stream: tour_end done", !!end && end.state === "done",
    end ? `state=${end.state}` : "no tour_end event");
}

// --- restore ---------------------------------------------------------------------
await gevCmd("stop_tour", {}, 3).catch(() => {});
if (CAST && RESTORE) {
  await pub({ type: "stop" });
  const idle = await poll(10000, async () => {
    const s = await screenState();
    return s && s.state === "idle" ? s : null;
  });
  check("restore: screen back to idle", !!idle);
}

console.log(failures.length
  ? `\n${failures.length} FAIL: ${failures.join(", ")}`
  : "\nall checks passed");
process.exit(failures.length ? 1 : 0);
