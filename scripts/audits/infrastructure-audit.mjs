#!/usr/bin/env node
/*
 * Infrastructure SSOT consistency audit.
 * Validates that health SSOT entries are complete and consistent, without doing live service checks.
 */
import { readFileSync } from 'fs';
import { join } from 'path';
import yaml from 'js-yaml';

const PROJECT_ROOT = '/home/tony/CascadeProjects/chaba';
const HEALTH_FILES = [
  'docs/ssot/infrastructure/ssot.health.home.yml',
  'docs/ssot/infrastructure/ssot.health.mobile.yml',
];
const VALUES_FILE = 'docs/ssot/infrastructure/ssot.values.yml';
const VALID_TYPES = new Set(['http', 'systemd', 'container', 'mount']);

function load(p) {
  const raw = readFileSync(join(PROJECT_ROOT, p), 'utf8');
  const doc = yaml.load(raw) || {};
  return doc;
}

function main() {
  const issues = [];
  const values = load(VALUES_FILE);

  for (const h of HEALTH_FILES) {
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
      if (!s.id) {
        issues.push(`${h}: missing service id`);
        continue;
      }
      if (fileIds.has(s.id)) {
        issues.push(`${h}: duplicate service id ${s.id}`);
      }
      fileIds.add(s.id);
      if (!s.name) issues.push(`${h}:${s.id}: missing name`);
      if (!s.type) issues.push(`${h}:${s.id}: missing type`);
      else if (!VALID_TYPES.has(s.type)) issues.push(`${h}:${s.id}: invalid type ${s.type}`);
      if (!s.expected_state) issues.push(`${h}:${s.id}: missing expected_state`);
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
        if (!s.path) issues.push(`${h}:${s.id}: missing mount path`);
        if (!s.expected_state) issues.push(`${h}:${s.id}: missing expected_state`);
      }
    }
  }

  // Check ports referenced in health files are in values
  const valuesText = readFileSync(join(PROJECT_ROOT, VALUES_FILE), 'utf8');
  const portRegex = /:(\d{2,5})\b/g;
  const healthText = HEALTH_FILES.map((h) => readFileSync(join(PROJECT_ROOT, h), 'utf8')).join('\n');
  let m;
  const badPorts = new Set();
  while ((m = portRegex.exec(healthText)) !== null) {
    const port = m[1];
    if (!valuesText.includes(port)) {
      badPorts.add(port);
    }
  }
  for (const port of badPorts) {
    issues.push(`port ${port} used in health SSOT but not defined in ssot.values.yml`);
  }

  const result = {
    ok: issues.length === 0,
    generated: new Date().toISOString(),
    files: HEALTH_FILES,
    total_services: ids.size,
    issues,
    total_issues: issues.length,
  };

  console.log(JSON.stringify(result, null, 2));
  process.exit(result.ok ? 0 : 1);
}

main();
