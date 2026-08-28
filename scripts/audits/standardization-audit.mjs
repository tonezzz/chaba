#!/usr/bin/env node
/*
 * Standardization / cross-reference audit.
 * Verifies that SSOT plans reference real files and that tool/service lists stay in sync.
 */
import { readFileSync, readdirSync, existsSync } from 'fs';
import { join, relative } from 'path';
import yaml from 'js-yaml';

const PROJECT_ROOT = '/home/tony/CascadeProjects/chaba';
const SSOT_DIR = join(PROJECT_ROOT, 'docs', 'ssot');
const SYSTEMD_DIR = join(PROJECT_ROOT, 'systemd');
const REPORTS_DIR = join(PROJECT_ROOT, 'reports', 'audits');

function load(p) {
  return yaml.load(readFileSync(p, 'utf8')) || {};
}

function main() {
  const issues = [];

  // 1. ssot.audit.yml audits must point to real scripts
  const auditSSOT = load(join(SSOT_DIR, 'infrastructure', 'ssot.audit.yml'));
  const auditNames = new Set();
  for (const a of auditSSOT.audits || []) {
    if (!a.name || !a.script) {
      issues.push(`audit missing name or script: ${JSON.stringify(a)}`);
      continue;
    }
    if (auditNames.has(a.name)) {
      issues.push(`duplicate audit name: ${a.name}`);
    }
    auditNames.add(a.name);
    const scriptPath = join(PROJECT_ROOT, a.script);
    if (!existsSync(scriptPath)) {
      issues.push(`missing audit script: ${a.script} for audit ${a.name}`);
    }
  }

  // 2. ssot.audit.yml groups must reference real audits
  for (const g of auditSSOT.groups || []) {
    for (const child of g.children || []) {
      if (!auditNames.has(child)) {
        issues.push(`group '${g.name}' references unknown audit: ${child}`);
      }
    }
  }

  // 3. ssot.automation.yml systemd units must exist
  const automation = load(join(SSOT_DIR, 'infrastructure', 'ssot.automation.yml'));
  for (const [key, entry] of Object.entries(automation)) {
    if (entry && typeof entry === 'object') {
      for (const k of ['service', 'timer']) {
        const unit = entry[k];
        if (unit) {
          const unitPath = join(SYSTEMD_DIR, unit);
          if (!existsSync(unitPath)) {
            issues.push(`automation '${key}' references missing ${k}: ${unit}`);
          }
        }
      }
    }
  }

  // 4. ssot.mcp-debug.yml registered_mcp_tools must be unique
  const mcpDebug = load(join(SSOT_DIR, 'infrastructure', 'ssot.mcp-debug.yml'));
  const registered = mcpDebug.registered_mcp_tools || [];
  const seen = new Set();
  for (const tool of registered) {
    if (seen.has(tool)) {
      issues.push(`duplicate registered_mcp_tool: ${tool}`);
    }
    seen.add(tool);
  }

  // 5. All scripts in scripts/audits should be registered in ssot.audit.yml
  const auditDir = join(PROJECT_ROOT, 'scripts', 'audits');
  const auditFiles = [];
  if (existsSync(auditDir)) {
    for (const f of readdirSync(auditDir)) {
      if (f.endsWith('.mjs') || f.endsWith('.sh') || f.endsWith('.js')) {
        auditFiles.push(join('scripts', 'audits', f));
      }
    }
  }
  const registeredScripts = new Set((auditSSOT.audits || []).map((a) => a.script));
  const ignored = new Set(['scripts/audits/run.mjs']);
  for (const f of auditFiles) {
    if (ignored.has(f)) continue;
    if (!registeredScripts.has(f)) {
      issues.push(`unregistered audit script: ${f}`);
    }
  }

  const result = {
    ok: issues.length === 0,
    generated: new Date().toISOString(),
    issues,
    total_issues: issues.length,
  };

  console.log(JSON.stringify(result, null, 2));
  process.exit(result.ok ? 0 : 1);
}

// missing mkdir import? we didn't. Remove reports write for now. The stdout is enough.
main();
