#!/usr/bin/env node
/**
 * Audit watchdog — meta-check that the audit suite itself is healthy.
 * Verifies reports/audits/summary.json exists and is fresh, and that the
 * last run had no error-severity failures. Writes a focus-inbox alert when
 * the suite is stale or failing, and auto-resolves the alert when healthy.
 * Run daily via chaba-audit-watchdog.timer (independent of the suite itself).
 */
import { existsSync, statSync, readFileSync, writeFileSync, rmSync } from "fs";
import { join } from "path";

const PROJECT_ROOT = new URL("../", import.meta.url).pathname.replace(/\/$/, "");
const SUMMARY = join(PROJECT_ROOT, "reports", "audits", "summary.json");
const INBOX = join(PROJECT_ROOT, "docs", "ssot", "focus-inbox");
const STALE_ALERT = join(INBOX, "audit-stale.yml");
const FAIL_ALERT = join(INBOX, "audit-failures.yml");

// The weekly suite should produce a summary within this window.
const MAX_AGE_DAYS = Number(process.env.AUDIT_MAX_AGE_DAYS || 8);

function writeAlert(path, title, subtitle, text) {
  writeFileSync(
    path,
    [
      `title: ${title}`,
      `subtitle: ${subtitle}`,
      "icon: alert",
      "focus:",
      "  label: Fix audit pipeline",
      "  text: |",
      ...text.split("\n").map((l) => `    ${l}`),
      "",
    ].join("\n"),
    "utf8"
  );
  console.log(`ALERT: wrote ${path}`);
}

let summary = null;
let ageDays = Infinity;
if (existsSync(SUMMARY)) {
  ageDays = (Date.now() - statSync(SUMMARY).mtimeMs) / 86400000;
  try {
    summary = JSON.parse(readFileSync(SUMMARY, "utf8"));
  } catch {
    summary = null;
  }
}

if (!summary) {
  writeAlert(
    STALE_ALERT,
    "Audit suite not running",
    "No readable reports/audits/summary.json",
    "The audit runner has never produced a summary on this host or the file is unreadable.\nRe-run: node scripts/audits/run.mjs"
  );
  process.exit(1);
}

if (ageDays > MAX_AGE_DAYS) {
  writeAlert(
    STALE_ALERT,
    "Audit suite stale",
    `Last summary ${ageDays.toFixed(1)}d old (max ${MAX_AGE_DAYS}d)`,
    `Generated: ${summary.generated || "unknown"}\nCheck chaba-audit.timer: systemctl --user status chaba-audit.timer\nRe-run: node scripts/audits/run.mjs`
  );
  process.exit(1);
}

// Fresh summary — resolve any staleness alert.
rmSync(STALE_ALERT, { force: true });

if (summary.ok === false) {
  const failed = (summary.results || [])
    .filter((r) => !r.ok && r.severity !== "warning")
    .map((r) => r.name)
    .join(", ");
  // run.mjs writes this alert itself; create it only if missing.
  if (!existsSync(FAIL_ALERT)) {
    writeAlert(
      FAIL_ALERT,
      "Audit suite failure",
      `Error-severity audits failing since ${summary.generated}`,
      `Failed audits: ${failed || "unknown"}\nReport: reports/audits/summary.md\nRe-run: node scripts/audits/run.mjs`
    );
  }
  console.log(`FAIL: ${failed}`);
  process.exit(1);
}

// Suite ran recently and is green — clear any leftover failure alert.
rmSync(FAIL_ALERT, { force: true });
console.log(`OK: audit suite healthy (summary ${ageDays.toFixed(1)}d old)`);
process.exit(0);
