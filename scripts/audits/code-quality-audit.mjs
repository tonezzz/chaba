#!/usr/bin/env node
/*
 * Code and formatting quality audit.
 * Runs the workspace lint/format checks and npm audit, returning a normalized report.
 */
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);
const PROJECT_ROOT = '/home/tony/CascadeProjects/chaba';

async function runCheck(label, command, timeoutMs = 120000) {
  try {
    const { stdout, stderr } = await execAsync(command, {
      cwd: PROJECT_ROOT,
      timeout: timeoutMs,
      maxBuffer: 10 * 1024 * 1024,
    });
    return { label, ok: true, output: (stdout + stderr).trim() };
  } catch (error) {
    return {
      label,
      ok: false,
      output: (error.stdout || '') + (error.stderr || ''),
      exit: error.code,
    };
  }
}

async function main() {
  const results = [];

  results.push(await runCheck('format:check', 'npm run format:check'));
  results.push(await runCheck('spell-check', 'npx cspell "docs/**/*.md"'));

  // Optional, may fail on network or if dependencies are fine
  const audit = await runCheck('npm-audit', 'npm audit --audit-level=moderate --json', 120000);
  if (!audit.ok && audit.output.includes('ECONNREFUSED') || audit.output.includes('ENETUNREACH')) {
    audit.note = 'npm audit could not reach registry; not counted as a hard failure';
    audit.ok = true;
  }
  results.push(audit);

  const issues = [];
  for (const r of results) {
    if (!r.ok) {
      const lines = r.output.split('\n').filter(l => l.includes('[warn]') || l.includes('[error]') || l.includes('Error'));
      issues.push(`${r.label}: failed with ${lines.length} reported issue(s)`);
    }
  }

  const result = {
    ok: issues.length === 0,
    generated: new Date().toISOString(),
    checks: results,
    total_checks: results.length,
    issues,
    total_issues: issues.length,
  };

  console.log(JSON.stringify(result, null, 2));
  process.exit(result.ok ? 0 : 1);
}

main().catch((e) => {
  console.error(JSON.stringify({ error: e.message }, null, 2));
  process.exit(1);
});
