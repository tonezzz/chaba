#!/usr/bin/env node
/**
 * SSOT Optimization Orchestrator
 *
 * Runs ssot-validate-all.mjs, captures bloat/data-isolation warnings,
 * and writes a non-destructive suggestions report.
 */
import { execSync } from 'child_process';
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync, watch } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO = join(__dirname, '..');
const REPORTS_DIR = join(REPO, 'reports');
const SSOT_DIR = join(REPO, 'docs', 'ssot');
const SUGGESTIONS = join(REPORTS_DIR, 'SSOT_OPTIMIZATION_SUGGESTIONS.md');
const METRICS = join(REPORTS_DIR, 'SSOT_OPTIMIZATION_METRICS.json');
const WARNINGS = join(REPORTS_DIR, 'SSOT_OPTIMIZATION_WARNINGS.json');
const HISTORY = join(REPORTS_DIR, 'SSOT_OPTIMIZATION_HISTORY.jsonl');
const HISTORY_DAYS = 90;

function pruneHistory() {
  if (!existsSync(HISTORY)) return;
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - HISTORY_DAYS);
  const lines = readFileSync(HISTORY, 'utf8').split('\n').filter(Boolean);
  const kept = [];
  for (const line of lines) {
    try {
      const entry = JSON.parse(line);
      if (new Date(entry.generated) >= cutoff) {
        kept.push(line);
      }
    } catch {
      // drop malformed lines
    }
  }
  writeFileSync(HISTORY, kept.join('\n') + (kept.length ? '\n' : ''), 'utf8');
}

function main() {
  const start = Date.now();
  const args = process.argv.slice(2).filter(a => a !== '--watch' && a !== '--fix').join(' ');
  const report = execSync(`${process.execPath} scripts/ssot-validate-all.mjs ${args}`, {
    cwd: REPO,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  const bloatWarnings = [];
  const dataWarnings = [];
  const otherWarnings = [];
  let currentFile = null;

  for (const line of report.split('\n')) {
    const fileMatch = line.match(/^Validating: (.+)$/);
    if (fileMatch) {
      currentFile = fileMatch[1];
      continue;
    }
    const warnMatch = line.match(/^    - (.+)$/);
    if (warnMatch && currentFile) {
      const text = warnMatch[1];
      if (text.startsWith('Bloat:')) {
        bloatWarnings.push({ file: currentFile, warning: text });
      } else if (text.startsWith('Data isolation:')) {
        dataWarnings.push({ file: currentFile, warning: text });
      } else {
        otherWarnings.push({ file: currentFile, warning: text });
      }
    }
  }

  let summary = `=== SSOT Optimization Suggestions ===\n\n`;
  summary += `Generated: ${new Date().toISOString()}\n`;
  summary += `Bloat warnings: ${bloatWarnings.length}\n`;
  summary += `Data-isolation warnings: ${dataWarnings.length}\n`;
  summary += `Other warnings: ${otherWarnings.length}\n\n`;

  summary += `## Bloat candidates (highest priority)\n\n`;
  if (bloatWarnings.length === 0) {
    summary += 'No bloat warnings.\n';
  } else {
    for (const w of bloatWarnings) {
      summary += `- \`${w.file}\`: ${w.warning}\n`;
    }
  }

  summary += `\n## Data isolation candidates\n\n`;
  if (dataWarnings.length === 0) {
    summary += 'No data-isolation warnings.\n';
  } else {
    for (const w of dataWarnings) {
      summary += `- \`${w.file}\`: ${w.warning}\n`;
    }
  }

  summary += `\n## Other warnings\n\n`;
  if (otherWarnings.length === 0) {
    summary += 'No other warnings.\n';
  } else {
    for (const w of otherWarnings) {
      summary += `- \`${w.file}\`: ${w.warning}\n`;
    }
  }

  summary += `\n---\n_Report produced by scripts/ssot-optimize.mjs in ${Date.now() - start}ms_\n`;

  if (!existsSync(REPORTS_DIR)) {
    mkdirSync(REPORTS_DIR, { recursive: true });
  }
  writeFileSync(SUGGESTIONS, summary, 'utf8');
  writeFileSync(METRICS, JSON.stringify({
    generated: new Date().toISOString(),
    bloat: bloatWarnings.length,
    data_isolation: dataWarnings.length,
    other: otherWarnings.length,
    files: 104,
  }, null, 2), 'utf8');
  writeFileSync(WARNINGS, JSON.stringify({
    generated: new Date().toISOString(),
    bloat: bloatWarnings,
    data_isolation: dataWarnings,
    other: otherWarnings,
  }, null, 2), 'utf8');

  const historyEntry = {
    generated: new Date().toISOString(),
    bloat: bloatWarnings.length,
    data_isolation: dataWarnings.length,
    other: otherWarnings.length,
    files: 104,
  };
  pruneHistory();
  appendFileSync(HISTORY, JSON.stringify(historyEntry) + '\n', 'utf8');

  console.log(`Wrote ${SUGGESTIONS}`);
  console.log(`Wrote ${METRICS}`);
  console.log(`Wrote ${WARNINGS}`);
}

function watchMode() {
  console.log(`👀 Watching ${SSOT_DIR} for SSOT changes...`);
  let timer = null;
  watch(SSOT_DIR, { recursive: true }, (event, filename) => {
    if (!filename || !filename.endsWith('.yml')) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      console.log(`\n📝 Change detected: ${filename}`);
      main();
    }, 500);
  });
}

function runFix() {
  try {
    execSync(`${process.execPath} scripts/ssot-optimize-to-inbox.mjs`, {
      cwd: REPO,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
    });
  } catch (err) {
    console.error(`[fix] inbox bridge failed: ${err.stderr || err.message}`);
  }
}

const args = process.argv.slice(2);
if (args.includes('--watch')) {
  watchMode();
} else {
  main();
  if (args.includes('--fix')) {
    runFix();
  }
}
