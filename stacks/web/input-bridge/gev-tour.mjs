#!/usr/bin/env node
"use strict";
// gev-tour — play a defined tour (ordered waypoints + dwell + narration
// cues) on a GEV display through the gev-gemini command relay, and emit a
// machine-readable checkpoint report a scenario can verify.
//
// Why this lives outside the app: bridge.py already exposes
//   POST /apps/gev-cmd/command  {name, args, screen?, pane?, wait?}
// which pushes a function_call frame to registered GEV remotes and (with
// wait>0, capped at 10s in the bridge) collects their tool_response
// frames. fly_to_location honors waitForArrival — its response carries
// arrived:true. That is the whole playback primitive a tour needs; no
// change to the (non-dispatchable) gods-eye-view repo is required.
//
// Tour format — JSON file (see docs/runbooks/gev-tours.md):
//   {
//     "id": "world-landmarks", "title": "...", "version": 1,
//     "defaults": {"dwell_s": 8, "arrival_timeout_s": 45,
//                  "camera": {"viewMode": "overview"}},
//     "stops": [
//       {"id": "london",
//        "target": {"locationId": "london"},           // OR {"query": "..."}
//                                                     // OR {"latitude","longitude"}
//        "camera": {"viewMode": "overview", "rangeM": 30000},
//        "dwell_s": 8,
//        "narration": "text cue — recorded AND drawn as a map label",
//        "annotate": [ {annotate_map annotation}, ... ],   // optional
//        "arrival_timeout_s": 45 },                      // optional per-stop
//       {"id": "finale", "tool": "zoom_to_globe", "args": {},
//        "dwell_s": 4}                                  // non-flight stops
//     ]
//   }
//
// Checkpoint contract (what a scenario verifies):
//   --report writes {tour, screen, pane, started_at, finished_at,
//   checkpoints:[{seq,id,tool,target,ok,arrived,verification,
//                 dispatched_at,reached_at,dwell_s,narration,error}],
//   reached_in_order, ok}. Checkpoints are appended strictly in stop
//   order; reached_at is monotonically non-decreasing. ok / exit 0 only
//   when every checkpoint arrived in order.
//
// Arrival is verified three ways, first match wins:
//   1. tool_response from fly_to_location(waitForArrival) within the
//      bridge's 10s wait cap -> verification:"tool_response"
//   2. get_current_view_state polls expose a flying->settled transition
//      (arrived:true / flying:false after in-flight was observed)
//      -> verification:"view_state"
//   3. view state exposes camera lat/lon within ~0.5 deg of a numeric
//      target -> verification:"coord_match"
//   Anything else after arrival_timeout_s -> checkpoint FAIL (honest).
//
// Usage:
//   node gev-tour.mjs --tour tours/world-landmarks.json [--screen 6]
//       [--pane 0] [--gev-cmd URL] [--report out.json] [--dry-run]
//       [--dwell-scale 0.5] [--stop-on-fail]
// Env: GEV_CMD, VCAST_SCREEN, VCAST_PANE.
// Defaults target the live tailnet deployment. Exits 0 on pass.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const arg = (name, dflt) => {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : dflt;
};
const has = (name) => process.argv.includes(`--${name}`);

const TOUR_PATH = arg("tour", process.env.GEV_TOUR || "");
const SCREEN = arg("screen", process.env.VCAST_SCREEN || "");
const PANE = arg("pane", process.env.VCAST_PANE || "");
const GEV_CMD = (arg("gev-cmd", process.env.GEV_CMD ||
  "https://tony-dell.taila0626a.ts.net/apps/gev-cmd")).replace(/\/+$/, "");
const REPORT = arg("report", "");
const DWELL_SCALE = parseFloat(arg("dwell-scale", "1"));
// Global cap on per-stop arrival wait — overrides defaults/per-stop
// arrival_timeout_s (selftests and smoke runs don't want 45s waits).
const ARRIVAL_CAP = parseFloat(arg("arrival-timeout", "0"));
const DRY = has("dry-run");
const STOP_ON_FAIL = has("stop-on-fail");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const nowIso = () => new Date().toISOString();

const failures = [];
function check(name, cond, detail = "") {
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
  if (!cond) failures.push(name);
}
function warn(name, detail = "") {
  console.log(`WARN  ${name}${detail ? `  (${detail})` : ""}`);
}

// ---------------------------------------------------------------------------
// Tour file loading + validation
// ---------------------------------------------------------------------------
function loadTour(p) {
  const errs = [];
  let t;
  try {
    t = JSON.parse(fs.readFileSync(p, "utf8"));
  } catch (e) {
    return { errs: [`cannot parse ${p}: ${e.message}`] };
  }
  if (!t || typeof t !== "object") return { errs: ["tour is not an object"] };
  if (!t.id || typeof t.id !== "string") errs.push("tour.id required");
  if (!Array.isArray(t.stops) || !t.stops.length)
    errs.push("tour.stops must be a non-empty array");
  const seen = new Set();
  (t.stops || []).forEach((s, i) => {
    const at = `stops[${i}]`;
    if (!s || typeof s !== "object") return errs.push(`${at}: not an object`);
    if (!s.id || typeof s.id !== "string") errs.push(`${at}.id required`);
    else if (seen.has(s.id)) errs.push(`${at}.id "${s.id}" duplicated`);
    seen.add(s.id);
    const hasTarget = s.target && typeof s.target === "object";
    const hasTool = typeof s.tool === "string" && s.tool;
    if (!hasTarget && !hasTool)
      errs.push(`${at} (${s.id || "?"}): needs target{} or tool`);
    if (hasTarget) {
      const tg = s.target;
      const forms = [];
      if (tg.locationId !== undefined) forms.push("locationId");
      if (tg.query !== undefined) forms.push("query");
      if (tg.latitude !== undefined || tg.longitude !== undefined)
        forms.push("latlon");
      if (!forms.length)
        errs.push(`${at}.target: need locationId | query | latitude+longitude`);
      if (forms.length > 1)
        errs.push(`${at}.target: exactly one form, got ${forms.join("+")}`);
      if (tg.latitude !== undefined &&
          (typeof tg.latitude !== "number" || Math.abs(tg.latitude) > 90))
        errs.push(`${at}.target.latitude out of range`);
      if (tg.longitude !== undefined &&
          (typeof tg.longitude !== "number" || Math.abs(tg.longitude) > 180))
        errs.push(`${at}.target.longitude out of range`);
    }
    if (s.dwell_s !== undefined &&
        (typeof s.dwell_s !== "number" || s.dwell_s < 0))
      errs.push(`${at}.dwell_s must be a number >= 0`);
    if (s.annotate !== undefined && !Array.isArray(s.annotate))
      errs.push(`${at}.annotate must be an array of annotations`);
  });
  return { tour: t, errs };
}

// ---------------------------------------------------------------------------
// Command relay client
// ---------------------------------------------------------------------------
async function cmdHealth() {
  try {
    const r = await fetch(`${GEV_CMD}/command/health`);
    return await r.json();
  } catch (e) {
    return { error: e.message };
  }
}
async function cmd(name, args = {}, wait = 0) {
  const body = { name, args, wait };
  if (SCREEN !== "") body.screen = parseInt(SCREEN, 10);
  if (PANE !== "") body.pane = parseInt(PANE, 10);
  const r = await fetch(`${GEV_CMD}/command`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return { status: r.status, data: await r.json().catch(() => ({})) };
}

// Recursive search for arrival-ish signals in a tool response / view state.
function findArrivedFlag(obj, depth = 0) {
  if (!obj || typeof obj !== "object" || depth > 6) return null;
  for (const [k, v] of Object.entries(obj)) {
    const lk = k.toLowerCase();
    if (lk === "arrived") return { key: k, value: !!v };
    if (["flying", "in_flight", "inflight", "flightinprogress",
         "is_flying", "camera_flying"].includes(lk))
      return { key: k, value: !v }; // arrived = NOT flying
  }
  for (const v of Object.values(obj)) {
    const r = findArrivedFlag(v, depth + 1);
    if (r) return r;
  }
  return null;
}

// Recursively find a {lat,lon}-ish numeric pair (camera position).
function findLatLon(obj, depth = 0) {
  if (!obj || typeof obj !== "object" || depth > 6) return null;
  const keys = Object.keys(obj);
  const latK = keys.find((k) => /^(lat|latitude|latdeg)$/i.test(k));
  const lonK = keys.find((k) => /^(lon|lng|longitude|londeg)$/i.test(k));
  if (latK && lonK &&
      typeof obj[latK] === "number" && typeof obj[lonK] === "number")
    return { lat: obj[latK], lon: obj[lonK] };
  for (const v of Object.values(obj)) {
    const r = findLatLon(v, depth + 1);
    if (r) return r;
  }
  return null;
}

// Did the client's tool_response say arrived / ok?
function responseArrived(responses) {
  for (const r of responses || []) {
    const resp = r && r.response;
    if (resp && typeof resp === "object") {
      if (resp.arrived === true) return true;
      if (resp.ok === false) return false; // cancelled/failed — honest
    }
  }
  return null; // no verdict
}

// ---------------------------------------------------------------------------
// Stop execution
// ---------------------------------------------------------------------------
function buildFlyArgs(stop, defaults) {
  const args = { ...(defaults.camera || {}), ...(stop.camera || {}) };
  const tg = stop.target || {};
  for (const k of ["locationId", "query", "latitude", "longitude"])
    if (tg[k] !== undefined) args[k] = tg[k];
  if (stop.wait_arrival !== false) args.waitForArrival = true;
  return args;
}

function buildNarrationAnnotations(stop) {
  const anns = Array.isArray(stop.annotate) ? [...stop.annotate] : [];
  if (stop.narration && stop.narrate_on_map !== false) {
    const label = String(stop.narration).slice(0, 120);
    const a = { type: "label", label, color: "cyan" };
    const tg = stop.target || {};
    if (tg.query) a.target = tg.query;
    else if (tg.locationId) a.target = tg.locationId;
    else if (tg.latitude !== undefined) {
      a.latitude = tg.latitude; a.longitude = tg.longitude;
    } else if (typeof stop.narration_target === "string") {
      a.target = stop.narration_target;
    }
    // Only drawable if we have an anchor; otherwise narration is a
    // report-only cue.
    if (a.target || a.latitude !== undefined) anns.unshift(a);
  }
  return anns;
}

async function runStop(stop, i, n, defaults, checkpoints) {
  const cp = {
    seq: i, id: stop.id, tool: stop.tool || "fly_to_location",
    target: stop.target || null, narration: stop.narration || null,
    dwell_s: stop.dwell_s ?? defaults.dwell_s ?? 6,
    dispatched_at: null, reached_at: null,
    delivered: 0, arrived: false, verification: null,
    ok: false, error: null,
  };
  checkpoints.push(cp);
  const tool = cp.tool;
  const args = stop.tool
    ? { ...(stop.args || {}) }
    : buildFlyArgs(stop, defaults);
  let timeout_s = stop.arrival_timeout_s ?? defaults.arrival_timeout_s ?? 45;
  if (ARRIVAL_CAP > 0) timeout_s = Math.min(timeout_s, ARRIVAL_CAP);

  if (DRY) {
    console.log(`  [dry] ${i + 1}/${n} ${cp.id}: ${tool} ${JSON.stringify(args)}` +
      (stop.narration ? `  narration="${stop.narration}"` : ""));
    const anns = buildNarrationAnnotations(stop);
    if (anns.length)
      console.log(`        annotate_map: ${JSON.stringify(anns)}`);
    cp.ok = true; cp.arrived = true; cp.verification = "dry_run";
    cp.dispatched_at = cp.reached_at = nowIso();
    return true;
  }

  cp.dispatched_at = nowIso();
  // Bridge caps wait at 10s — flights longer than that fall through to
  // the view-state poll loop below.
  const { status, data } = await cmd(tool, args, 10);
  cp.delivered = data.delivered || 0;
  if (status !== 200 || data.delivered === 0) {
    cp.error = data.error || `command endpoint status ${status}`;
    console.log(`  ${i + 1}/${n} ${cp.id}: NOT DELIVERED — ${cp.error}`);
    return false;
  }
  let verdict = responseArrived(data.responses);
  if (verdict === true) {
    cp.arrived = true; cp.verification = "tool_response";
    cp.reached_at = nowIso();
  } else if (verdict === false) {
    cp.error = "tool_response reported ok:false (flight cancelled/failed)";
    console.log(`  ${i + 1}/${n} ${cp.id}: FAILED — ${cp.error}`);
    return false;
  }

  // Fallback: poll get_current_view_state until arrival or timeout.
  if (!cp.arrived && tool === "fly_to_location") {
    const deadline = Date.now() + timeout_s * 1000;
    let sawFlying = false;
    const want = (stop.target && stop.target.latitude !== undefined)
      ? { lat: stop.target.latitude, lon: stop.target.longitude } : null;
    while (Date.now() < deadline) {
      await sleep(2500);
      const { data: vs } = await cmd("get_current_view_state", {}, 4);
      const resp = (vs.responses || [])[0];
      const state = resp && resp.response;
      if (!state) continue;
      const flag = findArrivedFlag(state);
      if (flag && flag.value === false) sawFlying = true;
      if (flag && flag.value === true) {
        cp.arrived = true; cp.verification = "view_state";
        cp.reached_at = nowIso();
        break;
      }
      if (sawFlying === false && flag === null) {
        // keep looking — no flight info yet
      }
      if (want) {
        const ll = findLatLon(state);
        if (ll && Math.abs(ll.lat - want.lat) < 0.5 &&
            Math.abs(ll.lon - want.lon) < 0.5) {
          cp.arrived = true; cp.verification = "coord_match";
          cp.reached_at = nowIso();
          break;
        }
      }
    }
  } else if (!cp.arrived) {
    // Non-flight stop: delivered ack is the checkpoint.
    cp.arrived = true; cp.verification = "delivered";
    cp.reached_at = nowIso();
  }

  if (!cp.arrived) {
    cp.error = `no arrival confirmation within ${timeout_s}s`;
    console.log(`  ${i + 1}/${n} ${cp.id}: FAILED — ${cp.error}`);
    return false;
  }
  cp.ok = true;
  console.log(`  ${i + 1}/${n} ${cp.id}: arrived (${cp.verification})` +
    (cp.narration ? ` — "${cp.narration}"` : ""));

  // Narration / annotation cue (fire-and-forget; annotate failure warns
  // but does not fail the checkpoint — the camera DID reach the stop).
  const anns = buildNarrationAnnotations(stop);
  if (anns.length) {
    const { data: ar } = await cmd("annotate_map",
      { annotations: anns, persist: stop.persist === true }, 3);
    if ((ar.delivered || 0) === 0)
      warn(`annotate ${cp.id}`, ar.error || "no delivery");
  }

  const dwell = cp.dwell_s * DWELL_SCALE;
  if (dwell > 0) await sleep(dwell * 1000);
  return true;
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
if (!TOUR_PATH) {
  console.error("usage: node gev-tour.mjs --tour <file.json> [--screen N] " +
    "[--pane P] [--gev-cmd URL] [--report out.json] [--dry-run] " +
    "[--dwell-scale F] [--stop-on-fail]");
  process.exit(2);
}
const { tour, errs } = loadTour(TOUR_PATH);
if (errs.length) {
  errs.forEach((e) => console.error(`FAIL  tour file: ${e}`));
  process.exit(1);
}
const defaults = tour.defaults || {};
console.log(`gev-tour  "${tour.title || tour.id}"  stops=${tour.stops.length}` +
  `  gev-cmd=${GEV_CMD}` +
  (SCREEN !== "" ? `  screen=${SCREEN}` : "  screen=broadcast") +
  (PANE !== "" ? `  pane=${PANE}` : "") +
  (DRY ? "  [dry-run]" : ""));

// Remote must be registered before we start driving.
if (!DRY) {
  const h = await cmdHealth();
  if (h.error) {
    console.error(`FAIL  command health unreachable: ${h.error}`);
    process.exit(1);
  }
  const remotes = h.remotes || [];
  const match = remotes.find((r) =>
    (SCREEN === "" || r.screen === parseInt(SCREEN, 10)) &&
    (PANE === "" || r.pane === parseInt(PANE, 10)));
  if (!match) {
    console.error(`FAIL  no GEV remote registered` +
      (SCREEN !== "" ? ` on screen ${SCREEN}` : "") +
      ` — remotes: ${JSON.stringify(remotes)}. ` +
      `Cast /apps/gev/ to the display first (see docs/runbooks/vcast-gev-verify-after-act.md).`);
    process.exit(1);
  }
  console.log(`remote: ${JSON.stringify(match)}  (${remotes.length} total)`);
}

const checkpoints = [];
const started = nowIso();
const t0 = Date.now();
for (let i = 0; i < tour.stops.length; i++) {
  const okStop = await runStop(tour.stops[i], i, tour.stops.length,
    defaults, checkpoints);
  if (!okStop && STOP_ON_FAIL) break;
}
const finished = nowIso();

// Order check: sequential execution makes this structural, but the flag
// is what a scenario asserts — keep it explicit.
const reached = checkpoints.filter((c) => c.ok);
const inOrder = reached.length === checkpoints.length &&
  checkpoints.every((c, i) => c.seq === i &&
    (i === 0 || c.reached_at >= checkpoints[i - 1].reached_at));
const ok = checkpoints.length === tour.stops.length &&
  checkpoints.every((c) => c.ok) && inOrder;

const report = {
  tour: { id: tour.id, title: tour.title || tour.id,
          version: tour.version || 1 },
  screen: SCREEN === "" ? null : parseInt(SCREEN, 10),
  pane: PANE === "" ? null : parseInt(PANE, 10),
  dry_run: DRY,
  started_at: started, finished_at: finished,
  duration_s: +((Date.now() - t0) / 1000).toFixed(1),
  checkpoints,
  reached_in_order: inOrder,
  ok,
};

check("all checkpoints reached in order", ok,
  `${reached.length}/${tour.stops.length}`);
if (REPORT) {
  fs.mkdirSync(path.dirname(path.resolve(REPORT)), { recursive: true });
  fs.writeFileSync(REPORT, JSON.stringify(report, null, 2));
  console.log(`report: ${REPORT}`);
} else if (has("json")) {
  console.log(JSON.stringify(report));
}
console.log(`gev-tour ${ok ? "PASS" : "FAIL"}  (${report.duration_s}s)`);
process.exit(ok ? 0 : 1);
