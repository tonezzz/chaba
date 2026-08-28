#!/usr/bin/env node
/**
 * SSOT optimization to focus-inbox bridge.
 * Reads SSOT_OPTIMIZATION_WARNINGS.json and turns bloat / data-isolation
 * findings into focus-inbox draft items, avoiding duplicates by file stem.
 */
import { existsSync, readdirSync, readFileSync, writeFileSync } from 'fs';
import { join } from 'path';
import yaml from 'js-yaml';

const PROJECT_ROOT = '/home/tony/CascadeProjects/chaba';
const REPORTS_DIR = join(PROJECT_ROOT, 'reports');
const WARNINGS_FILE = join(REPORTS_DIR, 'SSOT_OPTIMIZATION_WARNINGS.json');
const INBOX_DIR = join(PROJECT_ROOT, 'docs', 'ssot', 'focus-inbox');

function toTimestamp(date) {
  return date.toISOString().replace(/T/, '-').replace(/:/g, '').slice(0, 15);
}

function stem(file) {
  return file
    .replace(/^docs\//, '')
    .replace(/\.yml$/, '')
    .replace(/\//g, '-');
}

function existingInboxFor(file) {
  const key = stem(file);
  if (!existsSync(INBOX_DIR)) return null;
  for (const p of readdirSync(INBOX_DIR)) {
    if (p.startsWith('processed') || p.startsWith('archived')) continue;
    if (p.endsWith('-ssot-optimization.yml') && p.includes(`-${key}-`)) return p;
  }
  return null;
}

function makeInboxItem(file, warnings) {
  const lines = warnings.map((w) => `- ${w}`).join('\n');
  const text = `SSOT optimization detected issues in \`${file}\`:\n\n${lines}\n\nReview for bloat, data isolation, or obsolescence and either split/archive the file or resolve the warnings.`;
  const ts = toTimestamp(new Date());
  const label = `SSOT optimize: ${file}`;
  return {
    title: 'Focus Inbox Item',
    subtitle: `SSOT optimization finding for ${file}`,
    focus: {
      label,
      text,
      status: 'draft',
      priority: 'medium',
      tags: ['ssot', 'optimization', 'bloat', 'data-isolation'],
      missing_info: [
        'Does this file need splitting, archiving, or content cleanup?',
        'Which sections/items are the source of the warning?',
      ],
    },
  };
}

function main() {
  if (!existsSync(WARNINGS_FILE)) {
    console.log('[ssot-optimize-to-inbox] no warnings file; nothing to do');
    return 0;
  }

  const data = JSON.parse(readFileSync(WARNINGS_FILE, 'utf8'));
  const byFile = new Map();

  for (const type of ['bloat', 'data_isolation', 'other']) {
    for (const w of data[type] || []) {
      if (!byFile.has(w.file)) byFile.set(w.file, []);
      byFile.get(w.file).push(`${type}: ${w.warning}`);
    }
  }

  let created = 0;
  let skipped = 0;
  for (const [file, warnings] of byFile) {
    const existing = existingInboxFor(file);
    if (existing) {
      console.log(`[ssot-optimize-to-inbox] skip ${file}: existing ${existing}`);
      skipped += 1;
      continue;
    }

    const item = makeInboxItem(file, warnings);
    const filename = `${toTimestamp(new Date())}-${stem(file)}-ssot-optimization.yml`;
    const path = join(INBOX_DIR, filename);
    writeFileSync(
      path,
      yaml.safeDump(item, { sort_keys: false, allow_unicode: true, width: 120, default_flow_style: false })
    );
    console.log(`[ssot-optimize-to-inbox] created ${path} for ${file}`);
    created += 1;
  }

  console.log(`[ssot-optimize-to-inbox] created ${created}, skipped ${skipped}`);
  return 0;
}

process.exit(main());
