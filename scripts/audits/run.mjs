#!/usr/bin/env node
/**
 * Lightweight audit runner.
 * Calls each registered audit script and produces a normalized summary report.
 */
import { spawn } from 'child_process';
import { writeFileSync, mkdirSync } from 'fs';
import { join } from 'path';
import { fileURLToPath } from 'url';

const PROJECT_ROOT = '/home/tony/CascadeProjects/chaba';
const REPORTS_DIR = join(PROJECT_ROOT, 'reports', 'audits');

const DEFAULT_AUDITS = [
  { name: 'kb', command: 'node', args: ['scripts/kb-audit.mjs', '--json'] },
  { name: 'ssot', command: 'node', args: ['scripts/ssot-validate-all.mjs'] },
  { name: 'security-scan', command: 'node', args: ['scripts/security-scan.mjs', '--json'] },
];

const FULL_AUDITS = [
  ...DEFAULT_AUDITS,
  { name: 'security-audit', command: 'bash', args: ['scripts/security-audit.sh'] },
];


function runOne(audit) {
  return new Promise((resolve) => {
    const start = Date.now();
    const child = spawn(audit.command, audit.args, {
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
        command: `${audit.command} ${audit.args.join(' ')}`,
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
  const AUDITS = full ? FULL_AUDITS : DEFAULT_AUDITS;
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
    audit: 'chaba-audit-suite',
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

  const md = [
    '# Chaba Audit Summary',
    '',
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

main();
