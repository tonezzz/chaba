#!/usr/bin/env node
/*
 * Infrastructure SSOT consistency audit.
 * Validates that health SSOT entries are complete and consistent.
 * With --live it also performs real service checks and compares them to SSOT.
 */
import { readFileSync, readdirSync } from 'fs';
import { join, basename } from 'path';
import yaml from 'js-yaml';
import { spawn } from 'child_process';

const PROJECT_ROOT = '/home/tony/CascadeProjects/chaba';
const HEALTH_DIR = 'docs/ssot/infrastructure';
const VALID_TYPES = new Set(['http', 'systemd', 'container', 'mount', 'sse']);
const LIVE = process.argv.includes('--live');

function load(p) {
  const raw = readFileSync(join(PROJECT_ROOT, p), 'utf8');
  const doc = yaml.load(raw) || {};
  return doc;
}

function resolveHomeUrl(template) {
  // Use the home profile base_url from the main health SSOT
  return template.replace(/\{profile\}/g, 'http://tony-omen:8080');
}

function runSync(cmd, timeoutMs = 120000) {
  return new Promise((resolve) => {
    const [exe, ...args] = cmd.split(/\s+/);
    const proc = spawn(exe, args, { shell: false, stdio: ['ignore', 'pipe', 'pipe'] });
    let out = '';
    let err = '';
    proc.stdout.on('data', (d) => { out += d.toString(); });
    proc.stderr.on('data', (d) => { err += d.toString(); });
    proc.on('close', (code) => {
      resolve({ ok: code === 0, out: out.trim(), err: err.trim(), code });
    });
    setTimeout(() => {
      proc.kill();
      resolve({ ok: false, out, err: 'timeout', code: -1 });
    }, timeoutMs);
  });
}

async function mcpHealthCrossCheck(ssotIds, issues) {
  const r = await runSync('/usr/bin/python3 scripts/mcp-health-client.py get_health_status {}', 120000);
  if (!r.ok) {
    issues.push(`mcp-health cross-check failed: ${r.err}`);
    return;
  }
  let data;
  try {
    data = JSON.parse(r.out);
  } catch (e) {
    issues.push(`mcp-health cross-check returned invalid JSON: ${e.message}`);
    return;
  }
  const liveIds = new Set();
  (data.all_services || []).forEach(s => liveIds.add(s.id));
  const missing = [...ssotIds].filter(id => !liveIds.has(id));
  const orphans = [...liveIds].filter(id => !ssotIds.has(id));
  if (!liveIds.size) issues.push('mcp-health reports 0 services; check HEALTH_CONFIG or split-file loading');
  for (const id of missing) issues.push(`mcp-health is not checking SSOT service ${id}`);
  for (const id of orphans) issues.push(`mcp-health has unknown service ${id} not in SSOT`);
}

async function liveCheck(s) {
  if (s.type === 'http') {
    const url = resolveHomeUrl(s.url || '');
    const expected = Number(s.expected_status || 200);
    const timeout = Number(s.timeout || 5) * 1000;
    try {
      const controller = new AbortController();
      const t = setTimeout(() => controller.abort(), timeout);
      const res = await fetch(url, { signal: controller.signal });
      clearTimeout(t);
      if (res.status !== expected) {
        return `HTTP ${res.status} (expected ${expected}) for ${url}`;
      }
      return null;
    } catch (e) {
      return `HTTP fetch failed for ${url}: ${e.message}`;
    }
  }
  if (s.type === 'systemd') {
    const r = await runSync(`systemctl --user is-active ${s.service}`);
    if (!r.ok) return `systemd ${s.service} is not active`;
    return null;
  }
  if (s.type === 'container') {
    const r = await runSync(`docker ps -q -f name=${s.container}`);
    if (!r.out) return `container ${s.container} is not running (docker)`;
    return null;
  }
  if (s.type === 'mount') {
    const r = await runSync(`mountpoint -q ${s.mount_point}`);
    if (!r.ok) return `mount ${s.mount_point} is not a mountpoint`;
    return null;
  }
  return null;
}

async function main() {
  const issues = [];
  const liveIssues = [];
  let total = 0;
  const ssotIds = new Set();

  // Collect all health files: main home/mobile and split home.* files
  const files = [
    'docs/ssot/infrastructure/ssot.health.home.yml',
    'docs/ssot/infrastructure/ssot.health.mobile.yml',
  ];
  for (const f of readdirSync(join(PROJECT_ROOT, HEALTH_DIR))) {
    if (f.startsWith('ssot.health.home.') && f.endsWith('.yml') && f !== 'ssot.health.home.yml') {
      files.push(join(HEALTH_DIR, f));
    }
  }

  for (const h of files) {
    let doc;
    try {
      doc = load(h);
    } catch (e) {
      issues.push(`cannot parse ${h}: ${e.message}`);
      continue;
    }
    const fileIds = new Set();
    const services = doc.services || [];
    for (const s of services) {
      total++;
      if (!s.id) {
        issues.push(`${h}: missing service id`);
        continue;
      }
      if (fileIds.has(s.id)) {
        issues.push(`${h}: duplicate service id ${s.id}`);
      }
      fileIds.add(s.id);
      ssotIds.add(s.id);
      if (!s.name) issues.push(`${h}:${s.id}: missing name`);
      if (!s.type) issues.push(`${h}:${s.id}: missing type`);
      else if (!VALID_TYPES.has(s.type)) issues.push(`${h}:${s.id}: invalid type ${s.type}`);
      if (!s.category) issues.push(`${h}:${s.id}: missing category`);
      if (!s.profiles || !s.profiles.length) issues.push(`${h}:${s.id}: missing profiles`);

      if (s.type === 'http') {
        if (!s.url) issues.push(`${h}:${s.id}: missing url`);
        if (!s.expected_status && !s.expected_state) {
          issues.push(`${h}:${s.id}: missing expected_status or expected_state`);
        }
      }
      if (s.type === 'systemd') {
        if (!s.service) issues.push(`${h}:${s.id}: missing systemd service name`);
        if (!s.expected_state) issues.push(`${h}:${s.id}: missing expected_state`);
      }
      if (s.type === 'container') {
        if (!s.container) issues.push(`${h}:${s.id}: missing container name`);
        if (!s.expected_state) issues.push(`${h}:${s.id}: missing expected_state`);
      }
      if (s.type === 'mount') {
        if (!s.mount_point) issues.push(`${h}:${s.id}: missing mount_point`);
        if (!s.expected_state) issues.push(`${h}:${s.id}: missing expected_state`);
      }

      if (LIVE && s.url && s.type === 'http' && s.expected_status) {
        const err = await liveCheck(s);
        if (err) liveIssues.push(`${h}:${s.id}: ${err}`);
      } else if (LIVE && s.type !== 'http') {
        const err = await liveCheck(s);
        if (err) liveIssues.push(`${h}:${s.id}: ${err}`);
      }
    }
  }

  if (LIVE) {
    await mcpHealthCrossCheck(ssotIds, liveIssues);
  }

  const result = {
    ok: issues.length === 0 && liveIssues.length === 0,
    generated: new Date().toISOString(),
    live: LIVE,
    files,
    total_services: total,
    issues,
    total_issues: issues.length,
    live_issues: liveIssues,
    total_live_issues: liveIssues.length,
  };

  console.log(JSON.stringify(result, null, 2));
  process.exit(result.ok ? 0 : 1);
}

main().catch((e) => {
  console.error(JSON.stringify({ error: e.message }));
  process.exit(1);
});
