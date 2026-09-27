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
 *  - ssot.audit.hosts.yml: last_observed snapshots — stale when older than
 *    the matching audit-hosts/<host> node's cadence in ssot.reports.yml
 *    (fallback: STALE_HOST_SNAPSHOT_DAYS env, default 14d).
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
const REPORTS_REGISTRY = join(SSOT_DIR, "infrastructure", "ssot.reports.yml");

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

// Registry-declared cadences (ssot.reports.yml) -> days. "24h"/"7d"/"10m"/
// "daily"/"weekly" or bare seconds.
function cadenceDays(value) {
  if (value == null) return null;
  const s = String(value).trim().toLowerCase();
  const words = { hourly: 1 / 24, daily: 1, weekly: 7 };
  if (s in words) return words[s];
  const m = s.match(/^(\d+(?:\.\d+)?)([smhdw])$/);
  if (m) {
    const n = Number(m[1]);
    return n * { s: 1 / 86400, m: 1 / 1440, h: 1 / 24, d: 1, w: 7 }[m[2]];
  }
  const secs = Number(s);
  return Number.isFinite(secs) ? secs / 86400 : null;
}

const reportsRegistry = loadYaml(REPORTS_REGISTRY);
const nodeCadenceDays = {};
for (const n of reportsRegistry?.nodes || []) {
  const d = cadenceDays(n.cadence);
  if (n.id && d !== null) nodeCadenceDays[n.id] = d;
}

// --- security baseline last_verified dates ---
const baseline = loadYaml(BASELINE);
if (!baseline) {
  check("audit baseline readable", false, `${BASELINE} missing or unparseable`);
} else {
  const stale = [];
  const sections = [
    ["accepted_root_containers", (e) => `${e.name} (verified ${e.last_verified})`],
    ["accepted_public_endpoints", (e) => `${e.value} (verified ${e.last_verified})`],
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
    // Layered standard: the node's meta.generated_at is observed state and
    // refreshes on every audit-hosts run; ssot last_observed is only bumped
    // by manual --save-to-ssot, so prefer meta when present.
    const meta = loadYaml(
      join(PROJECT_ROOT, "reports", "audit-hosts", `meta.${name}.yml`)
    );
    const observed = meta?.generated_at || h.last_observed?.observed_at;
    if (!observed) continue; // never observed is informational, not stale
    const age = ageDays(observed);
    const maxAge =
      nodeCadenceDays[`audit-hosts/${name}`] ?? HOST_SNAPSHOT_MAX_AGE_DAYS;
    if (age !== null && age > maxAge) {
      staleHosts.push(`${name} (${age.toFixed(0)}d>${maxAge}d cadence)`);
    }
  }
  check(
    "host observed snapshots fresh",
    staleHosts.length === 0,
    staleHosts.length
      ? `stale vs registry cadence: ${staleHosts.join(", ")}`
      : "all observed snapshots within their registry cadence"
  );
}

const ok = checks.every((c) => c.ok);
console.log(JSON.stringify({ status: ok ? "ok" : "fail", checks }, null, 2));
process.exit(ok ? 0 : 1);
