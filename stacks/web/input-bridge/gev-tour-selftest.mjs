#!/usr/bin/env node
"use strict";
// gev-tour-selftest — run gev-tour.mjs against a stub gev-cmd relay and
// assert the checkpoint contract end-to-end without a real display.
//
// The stub implements GET /command/health (one fake remote) and
// POST /command, recording every call. fly_to_location replies with a
// tool_response {arrived:true}; a configured "stuck" stop id instead
// replies with no response so the runner must time out via view-state
// polling (stubbed to always report flying:true → never settles).
//
// Exercises:
//   1. happy path — all checkpoints ok, seq ordered, reached_at monotonic,
//      annotate_map fired after each narrated stop, exit 0
//   2. stuck stop — exit 1, reached_in_order=false, failed checkpoint
//      carries error + verification stayed null
//   3. no remote — health lists none -> runner refuses before dispatching
//
// Usage: node gev-tour-selftest.mjs   (exit 0 = pass)

import http from "node:http";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const RUNNER = path.join(HERE, "gev-tour.mjs");
const TOUR = path.join(HERE, "tours", "world-landmarks.json");

const failures = [];
function check(name, cond, detail = "") {
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
  if (!cond) failures.push(name);
}

function startStub({ stuckId = null, remotes = [{ screen: 6, pane: 0 }] } = {}) {
  const calls = [];
  const srv = http.createServer((req, res) => {
    const reply = (code, obj) => {
      const b = JSON.stringify(obj);
      res.writeHead(code, { "content-type": "application/json" });
      res.end(b);
    };
    if (req.method === "GET" && req.url === "/command/health")
      return reply(200, { ok: true, remote: remotes.length, remotes });
    if (req.method === "POST" && req.url === "/command") {
      let body = "";
      req.on("data", (c) => (body += c));
      req.on("end", () => {
        const m = JSON.parse(body || "{}");
        calls.push(m);
        const responses = [];
        if (m.wait > 0) {
          if (m.name === "fly_to_location") {
            const stuck = stuckId &&
              JSON.stringify(m.args).includes(stuckId);
            responses.push(stuck
              ? { id: "x", name: m.name, response: { ok: true } } // no arrived
              : { id: "x", name: m.name, response: { arrived: true } });
          } else if (m.name === "get_current_view_state") {
            responses.push({ id: "x", name: m.name,
              response: { camera: { flying: true,
                latitude: 0, longitude: 0 } } });
          } else {
            responses.push({ id: "x", name: m.name, response: { ok: true } });
          }
        }
        reply(200, { ok: true, delivered: remotes.length ? 1 : 0,
                     delivered_screens: [6], responses });
      });
      return;
    }
    reply(404, { error: "not found" });
  });
  return new Promise((resolve) => {
    srv.listen(0, "127.0.0.1", () =>
      resolve({ srv, calls, url: `http://127.0.0.1:${srv.address().port}` }));
  });
}

// NOTE: must be async spawn — spawnSync would block this process's event
// loop and the in-process stub server could never answer the runner.
function runTour(gevCmd, extra = []) {
  const report = path.join(
    fs.mkdtempSync(path.join(os.tmpdir(), "gev-tour-")), "report.json");
  return new Promise((resolve) => {
    const p = spawn("node",
      [RUNNER, "--tour", TOUR, "--gev-cmd", gevCmd, "--screen", "6",
       "--dwell-scale", "0", "--report", report, ...extra],
      { encoding: "utf8" });
    let stdout = "", stderr = "";
    p.stdout.on("data", (d) => (stdout += d));
    p.stderr.on("data", (d) => (stderr += d));
    const killer = setTimeout(() => p.kill("SIGKILL"), 120000);
    p.on("exit", (code) => {
      clearTimeout(killer);
      let parsed = null;
      try { parsed = JSON.parse(fs.readFileSync(report, "utf8")); } catch {}
      resolve({ code, stdout, stderr, report: parsed });
    });
  });
}

// --- case 1: happy path -----------------------------------------------------
{
  const stub = await startStub();
  const { code, report, stdout } = await runTour(stub.url);
  stub.srv.close();
  check("happy: exit 0", code === 0, `code=${code}`);
  check("happy: report parsed", !!report);
  if (report) {
    const tour = JSON.parse(fs.readFileSync(TOUR, "utf8"));
    check("happy: checkpoint count",
      report.checkpoints.length === tour.stops.length,
      `${report.checkpoints.length}/${tour.stops.length}`);
    check("happy: seq ordered",
      report.checkpoints.every((c, i) => c.seq === i));
    check("happy: reached_at monotonic",
      report.checkpoints.every((c, i) =>
        i === 0 || c.reached_at >= report.checkpoints[i - 1].reached_at));
    check("happy: all ok", report.checkpoints.every((c) => c.ok));
    check("happy: reached_in_order", report.reached_in_order === true);
    check("happy: fly stops verified by tool_response",
      report.checkpoints.filter((c) => c.tool === "fly_to_location")
        .every((c) => c.verification === "tool_response"));
    check("happy: narration recorded",
      report.checkpoints.filter((c) => c.narration).length ===
      tour.stops.filter((s) => s.narration).length);
  }
  const flyCalls = stub.calls.filter((c) => c.name === "fly_to_location");
  const annCalls = stub.calls.filter((c) => c.name === "annotate_map");
  check("happy: fly_to_location per fly stop", flyCalls.length === 6,
    `${flyCalls.length}`);
  check("happy: fly args carry waitForArrival",
    flyCalls.every((c) => c.args.waitForArrival === true));
  check("happy: narration cues drawn", annCalls.length >= 6,
    `${annCalls.length}`);
  check("happy: golden-gate sent lat/lon",
    flyCalls.some((c) => c.args.latitude === 37.8199 &&
                         c.args.longitude === -122.4783));
  check("happy: zoom_to_globe finale sent",
    stub.calls.some((c) => c.name === "zoom_to_globe"));
  check("happy: targeted screen=6 on every call",
    stub.calls.every((c) => c.screen === 6));
  if (code !== 0) console.log(stdout);
}

// --- case 2: stuck stop fails honestly --------------------------------------
{
  // Match the dubai stop via its locationId; --arrival-timeout caps the
  // view-state poll loop so the selftest doesn't burn the real 45s.
  const stub = await startStub({ stuckId: '"locationId":"dubai"' });
  const { code, report } = await runTour(stub.url, ["--arrival-timeout", "4"]);
  stub.srv.close();
  check("stuck: exit 1", code === 1, `code=${code}`);
  if (report) {
    const dubai = report.checkpoints.find((c) => c.id === "dubai");
    check("stuck: dubai checkpoint failed", dubai && dubai.ok === false);
    check("stuck: error recorded", !!(dubai && dubai.error),
      dubai && dubai.error);
    check("stuck: reached_in_order=false",
      report.reached_in_order === false);
    check("stuck: later stops still ran",
      report.checkpoints.slice(3).every((c) => c.ok));
  }
}

// --- case 3: no remote -> refuse ---------------------------------------------
{
  const stub = await startStub({ remotes: [] });
  const { code, stderr } = await runTour(stub.url);
  stub.srv.close();
  check("no-remote: exit 1", code === 1, `code=${code}`);
  check("no-remote: refuses with message",
    /no GEV remote/.test(stderr), (stderr || "").trim().split("\n").pop());
}

// --- case 4: dry-run validates + prints plan ---------------------------------
{
  const r = spawnSync("node",
    [RUNNER, "--tour", TOUR, "--dry-run", "--json"],
    { encoding: "utf8" });
  check("dry-run: exit 0", r.status === 0);
  check("dry-run: prints all stops",
    (r.stdout.match(/\[dry\]/g) || []).length === 7,
    `${(r.stdout.match(/\[dry\]/g) || []).length}`);
}

console.log(`\ngev-tour-selftest ${failures.length ? "FAIL" : "PASS"}` +
  (failures.length ? `  failed: ${failures.join(", ")}` : ""));
process.exit(failures.length ? 1 : 0);
