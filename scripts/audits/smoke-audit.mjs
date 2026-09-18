#!/usr/bin/env node
/**
 * Smoke-test audit — runs the scripts declared in
 * docs/ssot/infrastructure/ssot.test-manifest.yml systems.mcp.scripts.
 * Each entry is a repo-relative script run with python3 + declared args.
 * A non-zero exit or timeout is an issue; stderr noise is ignored.
 */
import { spawnSync } from "child_process";
import { readFileSync } from "fs";
import { join } from "path";
import yaml from "js-yaml";

const PROJECT_ROOT = new URL("../../", import.meta.url).pathname.replace(/\/$/, "");
const MANIFEST = join(PROJECT_ROOT, "docs", "ssot", "infrastructure", "ssot.test-manifest.yml");
const SCRIPT_TIMEOUT_MS = Number(process.env.SMOKE_TIMEOUT_MS || 120000);

const manifest = yaml.load(readFileSync(MANIFEST, "utf8"));
const scripts = manifest?.systems?.mcp?.scripts || [];

const issues = [];
const checks = [];

for (const entry of scripts) {
  const path = entry.path;
  const args = entry.args || [];
  const r = spawnSync("python3", [path, ...args], {
    cwd: PROJECT_ROOT,
    encoding: "utf8",
    timeout: SCRIPT_TIMEOUT_MS,
  });
  const ok = r.status === 0;
  checks.push({
    script: path,
    ok,
    exit_code: r.status,
    timed_out: r.error?.code === "ETIMEDOUT" || r.signal === "SIGTERM",
    tail: (r.stdout || "").trim().split("\n").slice(-3).join("\n"),
  });
  if (!ok) {
    issues.push(
      `${path}: ${r.error?.code === "ETIMEDOUT" ? "timed out" : `exit ${r.status}`}` +
        ((r.stderr || "").trim() ? ` — ${r.stderr.trim().split("\n").pop()}` : "")
    );
  }
}

const ok = issues.length === 0;
console.log(
  JSON.stringify(
    { ok, generated: new Date().toISOString(), scripts: checks.length, issues, checks },
    null,
    2
  )
);
process.exit(ok ? 0 : 1);
