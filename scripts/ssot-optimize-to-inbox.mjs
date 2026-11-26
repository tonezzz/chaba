#!/usr/bin/env node
/**
 * SSOT optimization to focus-inbox bridge.
 * Reads SSOT_OPTIMIZATION_WARNINGS.json and turns bloat / data-isolation
 * findings into focus-inbox draft items, avoiding duplicates by file stem.
 */
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "fs";
import { execFileSync } from "child_process";
import { dirname, join } from "path";
import { fileURLToPath } from "url";
import yaml from "js-yaml";

// Resolve the checkout this script lives in (was hardcoded to the
// chaba-tony-dell path — dead writes on hosts without that tree).
const PROJECT_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const REPORTS_DIR = join(PROJECT_ROOT, "reports");
const WARNINGS_FILE = join(REPORTS_DIR, "SSOT_OPTIMIZATION_WARNINGS.json");
const INBOX_DIR = join(PROJECT_ROOT, "docs", "ssot", "focus-inbox");
const BOARD_API = (process.env.BOARD_API ||
  "https://idc03.taila0626a.ts.net:10000").replace(/\/+$/, "");
const STATE_FILE = join(
  process.env.HOME || "/tmp",
  ".local/state/ssot-optimize-to-inbox-posted.json");

// Non-writer checkouts (stamped exec/readonly/job role) can't land inbox
// files — post via board-api /inbox instead, deduped by file stem in a
// local state file (card exec-checkout-generated-writes-focus-inb-da698a).
function checkoutRole() {
  try {
    const gitDir = execFileSync(
      "git", ["-C", PROJECT_ROOT, "rev-parse", "--absolute-git-dir"],
      { encoding: "utf8", timeout: 15000 }).trim();
    return readFileSync(join(gitDir, "chaba-role"), "utf8").trim();
  } catch {
    return "";
  }
}
const API_MODE = (() => {
  const role = checkoutRole();
  return Boolean(role) && role !== "served";
})();

function loadPosted() {
  try { return JSON.parse(readFileSync(STATE_FILE, "utf8")); }
  catch { return {}; }
}
function savePosted(m) {
  try {
    mkdirSync(dirname(STATE_FILE), { recursive: true });
    writeFileSync(STATE_FILE, JSON.stringify(m));
  } catch { /* best-effort */ }
}
async function postInbox(item) {
  const focus = item.focus || {};
  const body = {
    text: `SSOT optimization finding for \`${item.__file}\`:\n\n` +
      (focus.text || "").replace(/^SSOT optimization detected issues in `[^`]+`:\n\n/, ""),
    label: focus.label || item.title,
    priority: focus.priority || "medium",
    tags: focus.tags || [],
    owner: "tony",
    session: "ssot-optimize-to-inbox",
    missing_info: focus.missing_info,
  };
  try {
    const res = await fetch(`${BOARD_API}/inbox`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(20000),
    });
    return res.ok;
  } catch {
    return false;
  }
}

function toTimestamp(date) {
  return date.toISOString().replace(/T/, "-").replace(/:/g, "").slice(0, 15);
}

function stem(file) {
  return file
    .replace(/^docs\//, "")
    .replace(/\.yml$/, "")
    .replace(/\//g, "-");
}

function existingInboxFor(file) {
  const key = stem(file);
  if (!existsSync(INBOX_DIR)) return null;
  for (const p of readdirSync(INBOX_DIR)) {
    if (p.startsWith("processed") || p.startsWith("archived")) continue;
    if (p.endsWith("-ssot-optimization.yml") && p.includes(`-${key}-`)) return p;
  }
  return null;
}

function makeInboxItem(file, warnings) {
  const lines = warnings.map((w) => `- ${w}`).join("\n");
  const text = `SSOT optimization detected issues in \`${file}\`:\n\n${lines}\n\nReview for bloat, data isolation, or obsolescence and either split/archive the file or resolve the warnings.`;
  const ts = toTimestamp(new Date());
  const label = `SSOT optimize: ${file}`;
  return {
    title: "Focus Inbox Item",
    subtitle: `SSOT optimization finding for ${file}`,
    focus: {
      label,
      text,
      status: "draft",
      priority: "medium",
      tags: ["ssot", "optimization", "bloat", "data-isolation"],
      missing_info: [
        "Does this file need splitting, archiving, or content cleanup?",
        "Which sections/items are the source of the warning?",
      ],
    },
  };
}

async function main() {
  if (!existsSync(WARNINGS_FILE)) {
    console.log("[ssot-optimize-to-inbox] no warnings file; nothing to do");
    return 0;
  }

  const data = JSON.parse(readFileSync(WARNINGS_FILE, "utf8"));
  const byFile = new Map();

  for (const type of ["bloat", "data_isolation", "other"]) {
    for (const w of data[type] || []) {
      if (!byFile.has(w.file)) byFile.set(w.file, []);
      byFile.get(w.file).push(`${type}: ${w.warning}`);
    }
  }

  let created = 0;
  let skipped = 0;
  for (const [file, warnings] of byFile) {
    const item = { ...makeInboxItem(file, warnings), __file: file };
    if (API_MODE) {
      const stemKey = stem(file);
      const posted = loadPosted();
      if (posted[stemKey]) {
        console.log(`[ssot-optimize-to-inbox] skip ${file}: already posted`);
        skipped += 1;
        continue;
      }
      const ok = await postInbox(item);
      if (ok) {
        posted[stemKey] = new Date().toISOString();
        savePosted(posted);
        console.log(`[ssot-optimize-to-inbox] posted ${file} via /inbox`);
        created += 1;
      } else {
        console.error(`[ssot-optimize-to-inbox] /inbox post failed for ${file}`);
        skipped += 1;
      }
      continue;
    }

    const existing = existingInboxFor(file);
    if (existing) {
      console.log(`[ssot-optimize-to-inbox] skip ${file}: existing ${existing}`);
      skipped += 1;
      continue;
    }

    const filename = `${toTimestamp(new Date())}-${stem(file)}-ssot-optimization.yml`;
    const path = join(INBOX_DIR, filename);
    writeFileSync(
      path,
      yaml.safeDump(item, {
        sort_keys: false,
        allow_unicode: true,
        width: 120,
        default_flow_style: false,
      })
    );
    console.log(`[ssot-optimize-to-inbox] created ${path} for ${file}`);
    created += 1;
  }

  console.log(`[ssot-optimize-to-inbox] created ${created}, skipped ${skipped}`);
  return 0;
}

process.exit(main());
