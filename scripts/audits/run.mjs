#!/usr/bin/env node
/**
 * Lightweight audit runner.
 * Reads the audit list from docs/ssot/infrastructure/ssot.audit.yml,
 * runs each audit, and produces a normalized summary report.
 */
import { spawn } from 'child_process';
import { writeFileSync, readFileSync, mkdirSync, copyFileSync } from 'fs';
import { join } from 'path';
import yaml from 'js-yaml';

const PROJECT_ROOT = '/home/tony/CascadeProjects/chaba';
const REPORTS_DIR = join(PROJECT_ROOT, 'reports', 'audits');
const SSOT_FILE = join(PROJECT_ROOT, 'docs', 'ssot', 'infrastructure', 'ssot.audit.yml');

function loadAuditSSOT() {
  const text = readFileSync(SSOT_FILE, 'utf8');
  return yaml.load(text);
}

function getAudits(full = false) {
  const doc = loadAuditSSOT();
  const allAudits = (doc.audits || []).map((a) => ({
    name: a.name,
    command: a.command,
    args: a.args || [],
    script: a.script,
  }));
  const runs = full
    ? (doc.schedule?.full?.runs || allAudits.map((a) => a.name))
    : (doc.schedule?.default?.runs || allAudits.filter((a) => a.name !== 'security-audit').map((a) => a.name));
  return allAudits.filter((a) => runs.includes(a.name));
}

function runOne(audit) {
  return new Promise((resolve) => {
    const start = Date.now();
    const child = spawn(audit.command, [audit.script, ...audit.args], {
      cwd: PROJECT_ROOT,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (d) => { stdout += d.toString(); });
    child.stderr.on('data', (d) => { stderr += d.toString(); });
    child.on('close', (code) => {
      resolve({
        name: audit.name,
        command: `${audit.command} ${[audit.script, ...audit.args].join(' ')}`,
        ok: code === 0,
        duration_ms: Date.now() - start,
        exit_code: code,
        stdout: stdout.trim(),
        stderr: stderr.trim(),
      });
    });
  });
}

async function main() {
  const full = process.argv.slice(2).includes('--full');
  const AUDITS = getAudits(full);
  const doc = loadAuditSSOT();

  mkdirSync(REPORTS_DIR, { recursive: true });
  const started = new Date().toISOString();
  const results = [];
  for (const audit of AUDITS) {
    console.log(`Running audit: ${audit.name}`);
    const result = await runOne(audit);
    results.push(result);
    console.log(`  -> ${result.ok ? 'ok' : 'failed'} in ${result.duration_ms}ms`);
  }

  const summary = {
    audit: doc.title || 'chaba-audit-suite',
    ssot: SSOT_FILE,
    timestamp: started,
    generated: new Date().toISOString(),
    ok: results.every((r) => r.ok),
    summary: {
      total: results.length,
      passed: results.filter((r) => r.ok).length,
      failed: results.filter((r) => !r.ok).length,
    },
    results,
  };

  writeFileSync(join(REPORTS_DIR, 'summary.json'), JSON.stringify(summary, null, 2));

  // Publish the latest summary for the web audit report
  const webDataDir = join(PROJECT_ROOT, 'stacks', 'web', 'public', 'apps', 'audit', 'data');
  mkdirSync(webDataDir, { recursive: true });
  copyFileSync(join(REPORTS_DIR, 'summary.json'), join(webDataDir, 'summary.json'));
  copyFileSync(join(REPORTS_DIR, 'summary.md'), join(webDataDir, 'summary.md'));

  const md = [
    '# Chaba Audit Summary',
    '',
    `- SSOT: ${SSOT_FILE}`,
    `- Generated: ${summary.generated}`,
    `- Overall: ${summary.ok ? 'PASS' : 'FAIL'}`,
    `- Passed: ${summary.summary.passed}/${summary.summary.total}`,
    '',
    '| Audit | Status | Duration (ms) | Exit |',
    '|-------|--------|---------------|------|',
    ...results.map((r) => `| ${r.name} | ${r.ok ? 'PASS' : 'FAIL'} | ${r.duration_ms} | ${r.exit_code} |`),
    '',
    '## Details',
    '',
    ...results.map((r) => [
      `### ${r.name}`,
      '',
      `Command: \`${r.command}\``,
      '',
      '```',
      r.stdout || r.stderr || '(no output)',
      '```',
      '',
    ].join('\n')),
  ].join('\n');

  writeFileSync(join(REPORTS_DIR, 'summary.md'), md);

  if (summary.ok) {
    console.log('All audits passed.');
    process.exit(0);
  } else {
    console.error('Some audits failed. See reports/audits/summary.json');
    process.exit(1);
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
