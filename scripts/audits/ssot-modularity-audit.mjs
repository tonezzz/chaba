#!/usr/bin/env node
/*
 * SSOT modularity audit.
 * Checks that SSOT files are focused, not overly nested, and do not duplicate titles or concerns.
 */
import { readFileSync, readdirSync, writeFileSync, mkdirSync, existsSync } from 'fs';
import { join, relative } from 'path';
import yaml from 'js-yaml';

const PROJECT_ROOT = '/home/tony/CascadeProjects/chaba';
const SSOT_DIR = join(PROJECT_ROOT, 'docs', 'ssot');
const REPORTS_DIR = join(PROJECT_ROOT, 'reports', 'audits');
const SSOT_FILE = join(PROJECT_ROOT, 'docs', 'ssot', 'infrastructure', 'ssot.audit.yml');

function loadConfig() {
  try {
    const doc = yaml.load(readFileSync(SSOT_FILE, 'utf8'));
    const audit = (doc.audits || []).find((a) => a.name === 'ssot-modularity');
    return audit?.thresholds || {};
  } catch {
    return {};
  }
}

function nestingDepth(obj, depth = 0) {
  if (obj && typeof obj === 'object' && !Array.isArray(obj)) {
    const keys = Object.keys(obj);
    if (keys.length === 0) return depth;
    return Math.max(...keys.map((k) => nestingDepth(obj[k], depth + 1)));
  }
  if (Array.isArray(obj)) {
    return obj.length ? Math.max(...obj.map((i) => nestingDepth(i, depth + 1))) : depth;
  }
  return depth;
}

function main() {
  const thresholds = loadConfig();
  const maxWords = thresholds.max_words || 3000;
  const maxTopLevel = thresholds.max_top_level_keys || 16;
  const maxDepth = thresholds.max_nesting_depth || 8;
  const maxFilesWithSameTitle = thresholds.max_duplicate_titles || 1;
  const excludedTitles = new Set(thresholds.excluded_titles || []);
  const excludedPaths = (thresholds.excluded_paths || []).map((p) => p.endsWith('/') ? p : p + '/');

  const files = [];
  for (const p of readdirSync(SSOT_DIR, { recursive: true })) {
    if (typeof p !== 'string') continue;
    if (p.endsWith('.yml')) {
      files.push(join(SSOT_DIR, p));
    }
  }

  const items = files.map((p) => {
    const raw = readFileSync(p, 'utf8');
    const words = raw.split(/\s+/).filter(Boolean).length;
    let parsed = null;
    let parseError = null;
    try {
      parsed = yaml.load(raw);
    } catch (e) {
      parseError = e.message;
    }
    const topLevel = parsed && typeof parsed === 'object' ? Object.keys(parsed).length : 0;
    const depth = parsed ? nestingDepth(parsed) : 0;
    const title = parsed?.title || '';
    return {
      file: relative(PROJECT_ROOT, p),
      words,
      top_level: topLevel,
      depth,
      title,
      parse_error: parseError,
      issues: [],
    };
  });

  for (const item of items) {
    const isExcluded =
      excludedTitles.has(item.title) ||
      excludedPaths.some((p) => item.file.startsWith(p.endsWith('/') ? p : p + '/'));
    if (isExcluded) continue;
    if (item.parse_error) {
      item.issues.push(`parse error: ${item.parse_error}`);
    }
    if (item.words > maxWords) {
      item.issues.push(`exceeds max_words: ${item.words} > ${maxWords}`);
    }
    if (item.top_level > maxTopLevel) {
      item.issues.push(`too many top-level keys: ${item.top_level} > ${maxTopLevel}`);
    }
    if (item.depth > maxDepth) {
      item.issues.push(`too deeply nested: ${item.depth} > ${maxDepth}`);
    }
    if (!item.title) {
      item.issues.push('missing title');
    }
  }

  const isExcluded = (item) =>
    excludedTitles.has(item.title) ||
    excludedPaths.some((p) => item.file.startsWith(p));

  const titleCounts = {};
  for (const item of items) {
    if (item.title && !isExcluded(item)) {
      titleCounts[item.title] = (titleCounts[item.title] || 0) + 1;
    }
  }
  const duplicateTitles = Object.entries(titleCounts).filter(([, c]) => c > maxFilesWithSameTitle);
  for (const [title, count] of duplicateTitles) {
    for (const item of items) {
      if (item.title === title && !isExcluded(item)) {
        item.issues.push(`duplicate title '${title}' used ${count} times`);
      }
    }
  }

  const flagged = items.filter((i) => i.issues.length > 0);
  const result = {
    ok: true,
    generated: new Date().toISOString(),
    total: items.length,
    flagged: flagged.length,
    max_words: maxWords,
    max_top_level_keys: maxTopLevel,
    max_nesting_depth: maxDepth,
    max_duplicate_titles: maxFilesWithSameTitle,
    duplicate_titles: duplicateTitles.map(([title, count]) => ({ title, count })),
    flagged_files: flagged.map((i) => ({
      file: i.file,
      words: i.words,
      top_level: i.top_level,
      depth: i.depth,
      title: i.title,
      issues: i.issues,
    })),
  };

  mkdirSync(REPORTS_DIR, { recursive: true });
  writeFileSync(join(REPORTS_DIR, 'ssot-modularity.json'), JSON.stringify(result, null, 2));

  const md = [
    '# SSOT Modularity Audit',
    '',
    `- Generated: ${result.generated}`,
    `- Total: ${result.total}`,
    `- Flagged: ${result.flagged}`,
    '',
    '## Settings',
    '',
    `- max_words: ${maxWords}`,
    `- max_top_level_keys: ${maxTopLevel}`,
    `- max_nesting_depth: ${maxDepth}`,
    `- max_duplicate_titles: ${maxFilesWithSameTitle}`,
    '',
    '## Flagged files',
    '',
    ...flagged.map((i) => [
      `### ${i.file}`,
      '',
      ...i.issues.map((issue) => `- ${issue}`),
      '',
    ].join('\n')),
    ...(duplicateTitles.length ? [
      '## Duplicate titles',
      '',
      ...duplicateTitles.map(([title, count]) => `- '${title}' used ${count} times`),
    ] : []),
  ].join('\n');
  writeFileSync(join(REPORTS_DIR, 'ssot-modularity.md'), md);

  console.log(JSON.stringify(result, null, 2));
}

main();
