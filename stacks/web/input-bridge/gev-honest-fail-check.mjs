#!/usr/bin/env node
"use strict";
// gev-honest-fail-check — repo-side regression check for card gev-map:
// every vcast pane type (video/img/iframe) must surface a visible
// failure state instead of a black pane, the GEV page must carry the
// honest-fail watchdog + iPad msaaSamples:1 patch, and the staged
// ada-voice drop must be in place.
//
//   node gev-honest-fail-check.mjs
//
// Static assertions only (no browser, no server spawn) — the DOM-level
// e2e is the ada-voice scenario tests/scenarios-live/
// gev_pane_honest_fail.yaml (extended 2026-11-23 to every pane type).
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "../../..");
const VCAST = path.join(ROOT, "stacks/web/public/apps/vcast/index.html");
const GEV_DIR = path.join(ROOT, "stacks/web/public/apps/gev");
const PATCH = path.join(ROOT, "scripts/gev/patch-gev-dist.sh");
const DROP_DIR = path.join(ROOT, "integrations/ada-voice");

const failures = [];
function check(name, cond, detail = "") {
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
  if (!cond) failures.push(name);
}

// --- vcast display page: per-pane honest-fail for every pane type ----
const vcast = fs.readFileSync(VCAST, "utf8");
const inline = vcast.match(/<script>([\s\S]*)<\/script>/);
check("vcast inline script present", !!inline);
try { new Function(inline[1]); check("vcast inline script compiles", true); }
catch (e) { check("vcast inline script compiles", false, e.message); }

check("pfail overlay styled", /\.pfail\s*\{[^}]*position:\s*absolute/.test(vcast));
check("pfail element in pane0 markup", /<div class="pz">[^]*?<div class="pfail"><\/div>/.test(vcast));
check("pfail element in makePane template", vcast.includes(`<div class="pfail"></div>\`;`));
check("paneFail + paneOk helpers", vcast.includes("function paneFail") && vcast.includes("function paneOk"));
check("paneTeardown clears fail state", /function paneTeardown\(p\) \{\s*paneOk\(p\)/.test(vcast));
check("video error -> paneFail (non-HLS)", /paneFail\(p, `video failed — \$\{videoErr/.test(vcast));
check("video stall watchdog -> paneFail", vcast.includes("video did not start — no frames"));
check("hls retry veil (still retrying)", vcast.includes("still retrying"));
check("img onerror -> paneFail", vcast.includes('paneFail(p, "image failed to load")'));
check("img onload -> paneOk", /img\.onload = \(\) => \{[\s\S]{0,200}?paneOk\(p\)/.test(vcast));
check("iframe load watchdog -> paneFail", vcast.includes('paneFail(p, "page did not load")'));
check("same-origin probe armFrameProbe", vcast.includes("function armFrameProbe") && vcast.includes("__gevHonestFail"));
check("postMessage gev-honest-fail listener",
      vcast.includes('"gev-honest-fail"') && vcast.includes('"gev-honest-ok"') &&
      vcast.includes('addEventListener("message"'));

// --- GEV page: watchdog staged + injected, iPad patch kept -----------
const hfPath = path.join(GEV_DIR, "honest-fail.js");
check("gev honest-fail.js staged", fs.existsSync(hfPath));
if (fs.existsSync(hfPath)) {
  const hf = fs.readFileSync(hfPath, "utf8");
  try { new Function(hf); check("honest-fail.js compiles", true); }
  catch (e) { check("honest-fail.js compiles", false, e.message); }
  check("watchdog posts gev-honest-fail + ok", hf.includes('"gev-honest-fail"') && hf.includes('"gev-honest-ok"'));
  check("watchdog sets __gevHonestFail/__gevRenderOk", hf.includes("__gevHonestFail") && hf.includes("__gevRenderOk"));
  check("watchdog listens webglcontextlost", hf.includes("webglcontextlost") && hf.includes("webglcontextrestored"));
  check("watchdog has boot timeout", /BOOT_MS\s*=\s*\d+/.test(hf));
}
const gevHtml = fs.readFileSync(path.join(GEV_DIR, "index.html"), "utf8");
check("gev index.html injects honest-fail.js", gevHtml.includes("honest-fail.js"));

const bundle = fs.readdirSync(path.join(GEV_DIR, "assets"))
  .filter(f => /^index-.*\.js$/.test(f))
  .map(f => fs.readFileSync(path.join(GEV_DIR, "assets", f), "utf8"))
  .find(b => b.includes("msaaSamples"));
check("served bundle has msaaSamples", !!bundle);
if (bundle) {
  check("iPad msaaSamples:1 patch kept",
        bundle.includes("msaaSamples:/iPad|iPhone|iPod/.test(navigator.userAgent)?1:4"));
  check("no raw msaaSamples:4 left", !bundle.includes("msaaSamples:4"));
  check("api prefix patched", !/["'`]\/api\//.test(bundle) && bundle.includes("/apps/gev/api/"));
}

// --- patch script + ada-voice drop ------------------------------------
check("patch-gev-dist.sh present", fs.existsSync(PATCH));
if (fs.existsSync(PATCH)) {
  try {
    execFileSync("bash", [PATCH, "--self-test"], { stdio: "pipe" });
    check("patch-gev-dist.sh --self-test", true);
  } catch (e) { check("patch-gev-dist.sh --self-test", false, String(e).slice(0, 120)); }
}
check("scenario drop staged",
      fs.existsSync(path.join(DROP_DIR, "tests/scenarios-live/gev_pane_honest_fail.yaml")));
check("pane-pub driver patch staged",
      fs.existsSync(path.join(DROP_DIR, "scripts/scenario-live.pane-pub.patch")));

console.log(failures.length
  ? `\n${failures.length} FAIL — ${failures.join(", ")}`
  : "\nall checks passed");
process.exit(failures.length ? 1 : 0);
