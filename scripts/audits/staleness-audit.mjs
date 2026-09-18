#!/usr/bin/env node
/**
 * Staleness audit — flags declared exceptions/baselines that have aged past
 * their review window without being re-verified.
 *
 * Checked sources:
 *  - ssot.audit.baseline.yml: security exceptions with `last_verified` dates
 *    (accepted_root_containers, accepted_public_endpoints) — stale if >90d.
 *  - ssot.file-optimization.yml: bloat_exemptions are marked "review
 *    quarterly" — stale if config.last_updated is >90d.
 *  - ssot.audit.hosts.yml: last_observed snapshots — stale if >14d, since the
 *    daily audit-hosts job should keep them current.
 *
 * Output: JSON {status, checks:[{label, ok, details}]}. Exit 1 on any failure.
 * Stale items are warnings-by-design: the audit itself has severity_on_fail:
 * warning in ssot.audit.yml so it reports rather than gates.
 */
import { readFileSync } from "fs";
import { join } from "path";
import yaml from "js-yaml";

const PROJECT_ROOT = new URL("../../", import.meta.url).pathname.replace(/\/$/, "");
const SSOT_DIR = join(PROJECT_ROOT, "docs", "ssot");
const BASELINE = join(SSOT_DIR, "infrastructure", "ssot.audit.baseline.yml");
const OPTIMIZATION = join(SSOT_DIR, "ssot.file-optimization.yml");
const HOSTS = join(SSOT_DIR, "infrastructure", "ssot.audit.hosts.yml");

const BASELINE_MAX_AGE_DAYS = Number(process.env.STALE_BASELINE_DAYS || 90);
const EXEMPTION_MAX_AGE_DAYS = Number(process.env.STALE_EXEMPTION_DAYS || 90);
const HOST_SNAPSHOT_MAX_AGE_DAYS = Number(process.env.STALE_HOST_SNAPSHOT_DAYS || 14);

const DAY_MS = 86400000;
const checks = [];

function loadYaml(path) {
  try {
    return yaml.load(readFileSync(path, "utf8"));
  } catch {
    return null;
  }
}

function ageDays(dateStr) {
  const t = new Date(dateStr).getTime();
  if (Number.isNaN(t)) return null;
  return (Date.now() - t) / DAY_MS;
}

function check(label, ok, details) {
  checks.push({ label, ok, details });
}

// --- security baseline last_verified dates ---
const baseline = loadYaml(BASELINE);
if (!baseline) {
  check("audit baseline readable", false, `${BASELINE} missing or unparseable`);
} else {
  const stale = [];
  const sections = [
    ["accepted_root_containers", (e) => `${e.name} (verified ${e.last_verified})`],
    ["accepted_public_endpoints", (e) => `${e.endpoint} (verified ${e.last_verified})`],
  ];
  for (const [key, fmt] of sections) {
    for (const entry of baseline[key] || []) {
      const age = ageDays(entry.last_verified);
      if (age === null) {
        stale.push(`${fmt(entry)} — missing/invalid last_verified`);
      } else if (age > BASELINE_MAX_AGE_DAYS) {
        stale.push(`${fmt(entry)} — ${age.toFixed(0)}d old`);
      }
    }
  }
  check(
    "security baseline freshness",
    stale.length === 0,
    stale.length ? stale.join("; ") : "all exceptions verified within 90d"
  );
}

// --- bloat exemption review cadence ---
const opt = loadYaml(OPTIMIZATION);
if (!opt) {
  check("file-optimization config readable", false, `${OPTIMIZATION} missing or unparseable`);
} else {
  const updated = opt.config?.last_updated;
  const age = ageDays(updated);
  const nExempt =
    (opt.config?.bloat_exemptions?.hard_threshold || []).length +
    (opt.config?.bloat_exemptions?.review_threshold || []).length;
  check(
    "bloat exemption review cadence",
    age !== null && age <= EXEMPTION_MAX_AGE_DAYS,
    age === null
      ? `config.last_updated missing (${nExempt} exemptions)`
      : `${age.toFixed(0)}d since review (max ${EXEMPTION_MAX_AGE_DAYS}d; ${nExempt} exemptions)`
  );
}

// --- audit host observed snapshots ---
const hosts = loadYaml(HOSTS);
if (!hosts) {
  check("audit hosts SSOT readable", false, `${HOSTS} missing or unparseable`);
} else {
  const staleHosts = [];
  for (const [name, h] of Object.entries(hosts.hosts || {})) {
    const observed = h.last_observed?.observed_at;
    if (!observed) continue; // never observed is informational, not stale
    const age = ageDays(observed);
    if (age !== null && age > HOST_SNAPSHOT_MAX_AGE_DAYS) {
      staleHosts.push(`${name} (${age.toFixed(0)}d)`);
    }
  }
  check(
    "host observed snapshots fresh",
    staleHosts.length === 0,
    staleHosts.length
      ? `stale: ${staleHosts.join(", ")} (max ${HOST_SNAPSHOT_MAX_AGE_DAYS}d)`
      : "all observed snapshots within 14d"
  );
}

const ok = checks.every((c) => c.ok);
console.log(JSON.stringify({ status: ok ? "ok" : "fail", checks }, null, 2));
process.exit(ok ? 0 : 1);
