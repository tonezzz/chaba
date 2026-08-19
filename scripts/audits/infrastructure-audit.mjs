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
const VALID_TYPES = new Set(['http', 'systemd', 'container', 'mount']);

function load(p) {
  const raw = readFileSync(join(PROJECT_ROOT, p), 'utf8');
  const doc = yaml.load(raw) || {};
  return doc;
}

function main() {
  const issues = [];
  let total = 0;

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
      total++;
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
    }
  }

  const result = {
    ok: issues.length === 0,
    generated: new Date().toISOString(),
    files: HEALTH_FILES,
    total_services: total,
    issues,
    total_issues: issues.length,
  };

  console.log(JSON.stringify(result, null, 2));
  process.exit(result.ok ? 0 : 1);
}

main();
