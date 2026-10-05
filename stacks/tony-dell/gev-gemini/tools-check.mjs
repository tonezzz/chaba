#!/usr/bin/env node
// tools-check — drift guard for tools.json.
//
// GEV_REALTIME_TOOLS lives in the gods-eye-view source at vite.config.js;
// tools.json is a snapshot of it baked into the gev-gemini image. When the
// source declarations change and tools.json is not regenerated, the bridge
// serves Gemini stale declarations (the 2026-10-04 move_camera zoom/fly
// change needed exactly this regen). Gemini Live also REJECTS
// additionalProperties in function-declaration params, so the extracted
// snapshot is stripped recursively — the same cleaning bridge.py applies
// at load (_clean_schema), meaning tools.json is what the model sees.
//
//   node tools-check.mjs              check (default): exit 1 on drift
//   node tools-check.mjs --write      regenerate tools.json from source
//   node tools-check.mjs --config P   vite.config.js path (default
//                                     $GEV_VITE_CONFIG or ~/gods-eye-view)
//   node tools-check.mjs --tools P    committed tools.json (default: alongside
//                                     this script)
//
// Exit codes: 0 in sync / written, 1 drift, 2 usage or environment error.
"use strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const flag = (name) => args.includes(name);
const opt = (name) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : undefined;
};

const VITE_CONFIG = opt("--config") || process.env.GEV_VITE_CONFIG ||
  path.join(os.homedir(), "gods-eye-view", "vite.config.js");
const TOOLS_JSON = opt("--tools") || path.join(HERE, "tools.json");
const WRITE = flag("--write");

function die(msg, code = 2) {
  console.error(`tools-check: ${msg}`);
  process.exit(code);
}

// --- locate the GEV_REALTIME_TOOLS array literal -----------------------------
// Balanced-bracket scan that skips // /* */ comments, '..' ".." strings and
// `..` template literals so brackets inside strings can't desync the count.
function extractLiteral(src, constName) {
  const decl = src.indexOf(`${constName} = [`);
  if (decl < 0) return null;
  const start = src.indexOf("[", decl);
  let depth = 0, inStr = null, inTpl = false, inLine = false, inBlock = false, esc = false;
  for (let i = start; i < src.length; i++) {
    const c = src[i], n = src[i + 1];
    if (inLine) { if (c === "\n") inLine = false; continue; }
    if (inBlock) { if (c === "*" && n === "/") { inBlock = false; i++; } continue; }
    if (inStr) {
      if (esc) esc = false;
      else if (c === "\\") esc = true;
      else if (c === inStr) inStr = null;
      continue;
    }
    if (inTpl) {
      if (esc) esc = false;
      else if (c === "\\") esc = true;
      else if (c === "`") inTpl = false;
      continue;
    }
    if (c === "/" && n === "/") { inLine = true; continue; }
    if (c === "/" && n === "*") { inBlock = true; continue; }
    if (c === "`") { inTpl = true; continue; }
    if (c === '"' || c === "'") { inStr = c; continue; }
    if (c === "[" || c === "{") depth++;
    if (c === "]" || c === "}") {
      depth--;
      if (depth === 0) return src.slice(start, i + 1);
    }
  }
  return null;
}

// Same strip as bridge.py _clean_schema: Gemini Live rejects
// additionalProperties/additional_properties anywhere in the schema.
function cleanSchema(node) {
  if (Array.isArray(node)) return node.map(cleanSchema);
  if (!node || typeof node !== "object") return node;
  const out = {};
  for (const [k, v] of Object.entries(node)) {
    if (k === "additionalProperties" || k === "additional_properties") continue;
    out[k] = cleanSchema(v);
  }
  return out;
}

function canonical(tools) {
  return JSON.stringify(cleanSchema(tools), null, 2) + "\n";
}

// --- deep diff (path-level, so failures name the exact declaration) ----------
function diffPaths(a, b, at, out, cap) {
  if (out.length >= cap) return;
  if (Object.is(a, b) || JSON.stringify(a) === JSON.stringify(b)) return;
  const aObj = a && typeof a === "object", bObj = b && typeof b === "object";
  if (!aObj || !bObj || Array.isArray(a) !== Array.isArray(b)) {
    out.push(`${at}: committed=${JSON.stringify(a)?.slice(0, 80)} source=${JSON.stringify(b)?.slice(0, 80)}`);
    return;
  }
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  for (const k of keys) {
    if (!(k in a)) { out.push(`${at}.${k}: missing in committed tools.json`); }
    else if (!(k in b)) { out.push(`${at}.${k}: stale — not in GEV_REALTIME_TOOLS`); }
    else diffPaths(a[k], b[k], at ? `${at}.${k}` : k, out, cap);
    if (out.length >= cap) return;
  }
}

// --- load both sides ---------------------------------------------------------
if (!fs.existsSync(VITE_CONFIG)) die(`vite.config.js not found: ${VITE_CONFIG} (set --config or GEV_VITE_CONFIG)`);
const src = fs.readFileSync(VITE_CONFIG, "utf8");
const literal = extractLiteral(src, "GEV_REALTIME_TOOLS");
if (!literal) die(`GEV_REALTIME_TOOLS array not found in ${VITE_CONFIG}`);

let extracted;
try {
  extracted = new Function(`"use strict"; return (${literal});`)();
} catch (e) {
  die(`GEV_REALTIME_TOOLS literal did not evaluate: ${e.message}`);
}
if (!Array.isArray(extracted)) die("GEV_REALTIME_TOOLS did not evaluate to an array");

if (WRITE) {
  fs.writeFileSync(TOOLS_JSON, canonical(extracted));
  console.log(`tools-check: wrote ${extracted.length} declarations to ${TOOLS_JSON}`);
  process.exit(0);
}

if (!fs.existsSync(TOOLS_JSON)) {
  console.error(`tools-check: FAIL  ${TOOLS_JSON} missing — run: node ${path.basename(process.argv[1])} --write`);
  process.exit(1);
}
let committed;
try {
  committed = JSON.parse(fs.readFileSync(TOOLS_JSON, "utf8"));
} catch (e) {
  die(`tools.json is not valid JSON: ${e.message}`);
}

const normC = cleanSchema(committed);
const normS = cleanSchema(extracted);

const namesC = new Set(normC.map((t) => t.name));
const namesS = new Set(normS.map((t) => t.name));
const added = [...namesS].filter((n) => !namesC.has(n));
const removed = [...namesC].filter((n) => !namesS.has(n));

const diffs = [];
if (added.length) diffs.push(`tools missing from committed tools.json: ${added.join(", ")}`);
if (removed.length) diffs.push(`stale tools in committed tools.json: ${removed.join(", ")}`);
diffPaths(normC, normS, "", diffs, 40);

if (!diffs.length) {
  console.log(`tools-check: PASS  ${normS.length} declarations in ${TOOLS_JSON} match GEV_REALTIME_TOOLS (${VITE_CONFIG})`);
  process.exit(0);
}
console.log(`tools-check: FAIL  tools.json has drifted from GEV_REALTIME_TOOLS`);
for (const d of diffs) console.log(`  ${d}`);
console.log(`  regen: node ${path.basename(process.argv[1])} --write${opt("--config") ? " --config " + VITE_CONFIG : ""}`);
process.exit(1);
