#!/usr/bin/env node
// SSOT optimizer: non-destructive daily snapshot and suggestion report.
import { readdirSync, readFileSync, statSync, writeFileSync, existsSync, mkdirSync } from 'fs';
import { join, relative } from 'path';
import { fileURLToPath } from 'url';

const REPO = fileURLToPath(new URL('..', import.meta.url));
const SSOT_DIR = join(REPO, 'docs', 'ssot');
const REPORT_DIR = join(REPO, 'reports');
const DATA_DIR = join(REPO, 'data', 'ssot-optimization');

const REVIEW = { lines: 350, sections: 10, items: 45 };
const HARD = { lines: 750, sections: 12, items: 60 };

function isYaml(p) { return p.endsWith('.yml'); }
function isTemplate(p) { return p.includes('template') || p.includes('TEMPLATE'); }
function isInbox(p) { return p.includes('focus-inbox'); }

function listYaml(dir, base = '') {
  const out = [];
  for (const ent of readdirSync(dir, { withFileTypes: true })) {
    const p = join(base, ent.name);
    if (ent.isDirectory()) out.push(...listYaml(join(dir, ent.name), p));
    else if (isYaml(ent.name) && !isTemplate(ent.name) && !isInbox(p)) out.push({ rel: p, abs: join(dir, ent.name) });
  }
  return out;
}

function parseYaml(text) {
  // Simple structural parse without a heavy dependency.
  const lines = text.split(/\r?\n/);
  const sectionHeaders = [];
  const itemLabels = [];
  const statuses = [];
  const related = [];
  const dataIsolationHits = [];

  const ipRegex = /\b(127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b/g;
  const secretRegex = /(password|api_key|token|secret)\s*:\s*["']?[^\s"']+/gi;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\s*-?\s*title\s*:/.test(line)) {
      const m = line.match(/title\s*:\s*(.+)/);
      sectionHeaders.push(m ? m[1].trim() : `section-${i}`);
    }
    if (/^\s*-?\s*label\s*:/.test(line)) {
      const m = line.match(/label\s*:\s*(.+)/);
      if (m) itemLabels.push(m[1].trim());
    }
    if (/^\s*status\s*:/.test(line)) {
      const m = line.match(/status\s*:\s*(.+)/);
      if (m) statuses.push(m[1].trim());
    }
    if (/^\s*-?\s*path\s*:/.test(line) || /related_files\s*:/.test(line) || /path:/.test(line)) {
      const m = line.match(/(?:path|original_path)\s*:\s*["']?(.+?)["']?$/);
      if (m) related.push(m[1].trim());
    }
    if (ipRegex.test(line) || secretRegex.test(line)) {
      dataIsolationHits.push(`line ${i + 1}: ${line.trim().slice(0, 80)}`);
    }
  }

  const completed = statuses.filter(s => /completed|done|archived/.test(s)).length;
  const pending = statuses.filter(s => /pending|not_started|draft/.test(s)).length;

  return {
    lines: lines.length,
    sections: sectionHeaders.length,
    items: itemLabels.length,
    labels: itemLabels,
    statuses: { completed, pending, total: statuses.length },
    related,
    dataIsolationHits,
  };
}

function analyze() {
  const files = listYaml(SSOT_DIR);
  const metrics = [];
  const suggestions = [];
  const allLabels = new Map();
  let oversize = 0;
  let hardOversize = 0;

  for (const f of files) {
    const text = readFileSync(f.abs, 'utf8');
    const p = parseYaml(text);
    const rel = f.rel;

    const reviewFlags = [];
    if (p.lines > REVIEW.lines) reviewFlags.push('lines');
    if (p.sections > REVIEW.sections) reviewFlags.push('sections');
    if (p.items > REVIEW.items) reviewFlags.push('items');

    const hardFlags = [];
    if (p.lines > HARD.lines) hardFlags.push('lines');
    if (p.sections > HARD.sections) hardFlags.push('sections');
    if (p.items > HARD.items) hardFlags.push('items');

    if (reviewFlags.length) suggestions.push({ file: rel, type: 'bloat-review', detail: `exceeds review threshold for ${reviewFlags.join(', ')}` });
    if (hardFlags.length) { suggestions.push({ file: rel, type: 'bloat-hard', detail: `exceeds hard threshold for ${hardFlags.join(', ')}` }); hardOversize++; }
    if (p.lines > REVIEW.lines) oversize++;

    for (const label of p.labels) {
      allLabels.set(label, (allLabels.get(label) || []).concat(rel));
    }

    if (p.dataIsolationHits.length) suggestions.push({ file: rel, type: 'data-isolation', detail: `found ${p.dataIsolationHits.length} candidate IP/secret patterns`, examples: p.dataIsolationHits.slice(0, 3) });

    for (const rp of p.related) {
      const target = join(REPO, rp);
      if (!existsSync(target)) suggestions.push({ file: rel, type: 'broken-reference', detail: `related path not found: ${rp}` });
    }

    metrics.push({
      file: rel,
      lines: p.lines,
      sections: p.sections,
      items: p.items,
      statuses: p.statuses,
      review_flags: reviewFlags,
      hard_flags: hardFlags,
      data_isolation_hits: p.dataIsolationHits.length,
      broken_references: p.related.filter(rp => !existsSync(join(REPO, rp))).length,
    });
  }

  const duplicateLabels = [...allLabels.entries()].filter(([, v]) => v.length > 1);
  for (const [label, files] of duplicateLabels) {
    if (label === 'Reduce focus.current bloat' || !label) continue; // known repeated quick win
    suggestions.push({ type: 'redundancy', label, files, detail: `label appears in ${files.length} files` });
  }

  const summary = {
    generated: new Date().toISOString(),
    files_scanned: files.length,
    total_lines: metrics.reduce((a, m) => a + m.lines, 0),
    oversize_review: oversize,
    oversize_hard: hardOversize,
    data_isolation_candidates: suggestions.filter(s => s.type === 'data-isolation').length,
    broken_references: suggestions.filter(s => s.type === 'broken-reference').length,
    redundancy_candidates: duplicateLabels.length,
  };

  return { summary, metrics, suggestions };
}

function main() {
  const result = analyze();

  // Write metrics
  [REPORT_DIR, DATA_DIR].forEach(d => {
    if (!existsSync(d)) mkdirSync(d, { recursive: true });
  });

  writeFileSync(join(REPORT_DIR, 'SSOT_OPTIMIZATION_METRICS.json'), JSON.stringify(result, null, 2));

  const md = [
    '# SSOT Optimization Suggestions',
    '',
    `Generated: ${result.summary.generated}`,
    '',
    `## Summary`,
    '',
    `- Files scanned: ${result.summary.files_scanned}`,
    `- Total lines: ${result.summary.total_lines}`,
    `- Files above review threshold: ${result.summary.oversize_review}`,
    `- Files above hard threshold: ${result.summary.oversize_hard}`,
    `- Data-isolation candidates: ${result.summary.data_isolation_candidates}`,
    `- Broken references: ${result.summary.broken_references}`,
    `- Redundancy candidates: ${result.summary.redundancy_candidates}`,
    '',
    `## Top suggestions`,
    '',
    ...result.suggestions.map(s => `- **${s.type}** ${s.file || s.label || ''}: ${s.detail}`).slice(0, 50),
    '',
    `## Full metrics`,
    '',
    'See `reports/SSOT_OPTIMIZATION_METRICS.json`.',
  ].join('\n');
  writeFileSync(join(REPORT_DIR, 'SSOT_OPTIMIZATION_SUGGESTIONS.md'), md);

  console.log(`[ssot-optimize] scanned ${result.summary.files_scanned} files`);
  console.log(`[ssot-optimize] wrote reports/SSOT_OPTIMIZATION_METRICS.json and reports/SSOT_OPTIMIZATION_SUGGESTIONS.md`);
  return 0;
}

process.exit(main());
