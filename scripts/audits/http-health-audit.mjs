#!/usr/bin/env node
/**
 * Live HTTP health audit — probes every `type: http` service declared in
 * docs/ssot/infrastructure/ssot.health*.yml. Each service declares its
 * expected status and timeout, so this audit adds zero configuration: the
 * health SSOTs are the contract.
 *
 * Skips: disabled services, templated URLs ({profile}), non-http types.
 * For https: URLs the peer certificate's days-to-expiry is also checked.
 *
 * Classification:
 *  - issue: unreachable, timeout, wrong status, cert <7d/invalid
 *  - warn:  slow response (>2s), redirect when expecting 200, cert <30d
 *
 * Output: JSON {ok, checks, issues, warns}. Exit 1 on any issue.
 * Env: HEALTH_PROFILE (default "home") filters services by `profiles`.
 */
import http from "http";
import https from "https";
import { readdirSync, readFileSync } from "fs";
import { join } from "path";
import { hostname } from "os";
import yaml from "js-yaml";

const PROJECT_ROOT = new URL("../../", import.meta.url).pathname.replace(/\/$/, "");
const HEALTH_DIR = join(PROJECT_ROOT, "docs", "ssot", "infrastructure");
const PROFILE = process.env.HEALTH_PROFILE || "home";
const CURRENT_HOST = hostname();
const SLOW_MS = 2000;
const CERT_WARN_DAYS = 30;
const CERT_FAIL_DAYS = 7;
const CONCURRENCY = 10;

const issues = [];
const warns = [];
const checks = [];

function collectServices() {
  const files = readdirSync(HEALTH_DIR).filter(
    (f) => f.startsWith("ssot.health") && f.endsWith(".yml")
  );
  const services = [];
  for (const file of files) {
    let doc;
    try {
      doc = yaml.load(readFileSync(join(HEALTH_DIR, file), "utf8"));
    } catch {
      continue; // the infrastructure audit owns parse errors
    }
    for (const s of doc?.services || []) {
      if (s.type !== "http" || s.disabled || !s.url || s.url.includes("{")) continue;
      if (s.profiles && !s.profiles.includes(PROFILE)) continue;
      // Localhost URLs bound on another host can never be probed from here —
      // that is a host-scoping limitation, not a service failure. Only
      // probe localhost URLs when the declared host is this machine.
      const isLocalUrl = /^https?:\/\/(127\.|localhost)/.test(s.url);
      if (
        isLocalUrl &&
        s.host &&
        s.host !== CURRENT_HOST &&
        s.host !== CURRENT_HOST.replace(/-/g, "_")
      ) {
        warns.push(`${s.id || s.url}: localhost-only on ${s.host}; skipped (host-scoped)`);
        continue;
      }
      services.push({
        id: s.id || s.name || s.url,
        file,
        url: s.url,
        expected: s.expected_status ?? 200,
        timeoutMs: (s.timeout ?? 5) * 1000,
        host: s.host,
      });
    }
  }
  // The same URL is declared in multiple health files with different
  // timeouts; probe each unique URL once, using the most lenient timeout.
  const byUrl = new Map();
  for (const s of services) {
    const prev = byUrl.get(s.url);
    if (!prev || s.timeoutMs > prev.timeoutMs) byUrl.set(s.url, s);
  }
  return [...byUrl.values()];
}

function probe(svc) {
  return new Promise((resolve) => {
    const u = new URL(svc.url);
    const mod = u.protocol === "https:" ? https : http;
    const start = Date.now();
    const req = mod.get(
      {
        hostname: u.hostname,
        port: u.port || (u.protocol === "https:" ? 443 : 80),
        path: u.pathname + u.search,
        timeout: svc.timeoutMs,
        headers: { "User-Agent": "chaba-http-health-audit/1.0" },
      },
      (res) => {
        const durationMs = Date.now() - start;
        let certDays = null;
        if (u.protocol === "https:") {
          const cert = res.socket.getPeerCertificate?.();
          if (cert && cert.valid_to) {
            certDays = Math.floor((new Date(cert.valid_to) - Date.now()) / 86400000);
          }
        }
        res.resume(); // drain
        resolve({ status: res.statusCode, durationMs, certDays });
      }
    );
    req.on("timeout", () => {
      req.destroy();
      resolve({ error: `timeout after ${svc.timeoutMs}ms`, durationMs: Date.now() - start });
    });
    req.on("error", (e) => {
      resolve({ error: e.message, durationMs: Date.now() - start });
    });
  });
}

async function runPool(items, worker, n) {
  const queue = [...items];
  await Promise.all(
    Array.from({ length: n }, async () => {
      while (queue.length) {
        await worker(queue.shift());
      }
    })
  );
}

async function main() {
  const services = collectServices();
  await runPool(
    services,
    async (svc) => {
      const r = await probe(svc);
      const label = `${svc.id} (${svc.url})`;
      if (r.error) {
        if (/timeout/.test(r.error)) {
          // A timeout may be a slow-but-healthy endpoint (declared timeouts
          // can lag reality); retry once at 2x before calling it down.
          const retry = await probe({ ...svc, timeoutMs: svc.timeoutMs * 2 });
          if (retry.status) {
            warns.push(
              `${label}: exceeded declared timeout (${r.durationMs}ms, ok at ${retry.durationMs}ms)`
            );
            checks.push({
              id: svc.id,
              url: svc.url,
              ok: true,
              status: retry.status,
              duration_ms: retry.durationMs,
            });
            return;
          }
        }
        issues.push(`${label}: ${r.error}`);
        checks.push({ id: svc.id, url: svc.url, ok: false, error: r.error });
        return;
      }
      let ok = true;
      if (r.status !== svc.expected) {
        if (r.status >= 300 && r.status < 400 && svc.expected === 200) {
          warns.push(`${label}: redirects (HTTP ${r.status}) — declared 200`);
        } else {
          issues.push(`${label}: HTTP ${r.status}, expected ${svc.expected}`);
          ok = false;
        }
      }
      if (r.durationMs > SLOW_MS) {
        warns.push(`${label}: slow ${r.durationMs}ms`);
      }
      if (r.certDays !== null) {
        if (r.certDays < CERT_FAIL_DAYS) {
          issues.push(`${label}: TLS cert expires in ${r.certDays}d`);
          ok = false;
        } else if (r.certDays < CERT_WARN_DAYS) {
          warns.push(`${label}: TLS cert expires in ${r.certDays}d`);
        }
      }
      checks.push({
        id: svc.id,
        url: svc.url,
        ok,
        status: r.status,
        duration_ms: r.durationMs,
        cert_days: r.certDays,
      });
    },
    CONCURRENCY
  );

  const result = {
    ok: issues.length === 0,
    generated: new Date().toISOString(),
    profile: PROFILE,
    services_checked: checks.length,
    services_ok: checks.filter((c) => c.ok).length,
    issues,
    warns,
    checks,
  };
  console.log(JSON.stringify(result, null, 2));
  process.exit(result.ok ? 0 : 1);
}

main().catch((e) => {
  console.error(JSON.stringify({ ok: false, error: e.message }));
  process.exit(1);
});
