#!/usr/bin/env node
/*
 * KB modularity audit.
 * Checks that each KB entry is focused, not oversized, not duplicated, and links to SSOT where appropriate.
 */
import { readFileSync, readdirSync, writeFileSync, mkdirSync } from 'fs';
import { join, relative } from 'path';
import yaml from 'js-yaml';

const PROJECT_ROOT = '/home/tony/CascadeProjects/chaba-tony-dell';
const KB_DIR = join(PROJECT_ROOT, 'docs', 'kb');
const REPORTS_DIR = join(PROJECT_ROOT, 'reports', 'audits');
const SSOT_FILE = join(PROJECT_ROOT, 'docs', 'ssot', 'infrastructure', 'ssot.audit.yml');

function loadConfig() {
  try {
    const doc = yaml.load(readFileSync(SSOT_FILE, 'utf8'));
    const audit = (doc.audits || []).find((a) => a.name === 'kb-modularity');
    return audit?.thresholds || {};
  } catch {
    return {};
  }
}

function tokenize(text) {
  return [...new Set(text.toLowerCase().split(/\W+/).filter((w) => w.length > 2))];
}

function jaccard(a, b) {
  const setA = new Set(a);
  const setB = new Set(b);
  const intersection = a.filter((x) => setB.has(x)).length;
  return intersection / (setA.size + setB.size - intersection || 1);
}

function extractText(raw) {
  return raw.replace(/^---[\s\S]*?---\n*/, '').trim();
}

function main() {
  const thresholds = loadConfig();
  const maxWords = thresholds.max_words || 1200;
  const maxHeadings = thresholds.max_headings || 5;
  const minLinks = thresholds.min_links || 0;
  const similarityThreshold = thresholds.max_similarity || 0.85;
  const excludedFiles = new Set(thresholds.excluded_files || []);
  const excludedPatterns = (thresholds.excluded_patterns || []).map((p) => new RegExp(p));

  const files = [];
  for (const f of readdirSync(KB_DIR)) {
    if (f.endsWith('.md')) {
      files.push(join(KB_DIR, f));
    }
  }

  const items = files.map((p) => {
    const raw = readFileSync(p, 'utf8');
    const text = extractText(raw);
    const words = text.split(/\s+/).filter(Boolean);
    const headings = (text.match(/^#{1,6}\s+/gm) || []).length;
    const category = raw.match(/^category:\s*(.+)$/m)?.[1]?.trim() || 'missing';
    const links = (text.match(/\[.+?\]\(.+?\)/g) || []).length;
    const ssotLinks = (text.match(/docs\/ssot\//g) || []).length;
    const tokens = tokenize(text);
    return {
      file: relative(PROJECT_ROOT, p),
      words: words.length,
      headings,
      category,
      links,
      ssot_links: ssotLinks,
      tokens,
      issues: [],
    };
  });

  for (const item of items) {
    const isExcluded =
      excludedFiles.has(item.file) ||
      excludedPatterns.some((r) => r.test(item.file));
    if (isExcluded) continue;
    if (item.words > maxWords) {
      item.issues.push(`exceeds max_words: ${item.words} > ${maxWords}`);
    }
    if (item.headings > maxHeadings) {
      item.issues.push(`exceeds max_headings: ${item.headings} > ${maxHeadings}`);
    }
    if (item.category === 'missing') {
      item.issues.push('missing category');
    }
    if (item.links < minLinks) {
      item.issues.push(`too few links: ${item.links} < ${minLinks}`);
    }
  }

  const duplicates = [];
  for (let i = 0; i < items.length; i++) {
    for (let j = i + 1; j < items.length; j++) {
      const a = items[i];
      const b = items[j];
      const score = jaccard(a.tokens, b.tokens);
      if (score >= similarityThreshold) {
        duplicates.push({ a: a.file, b: b.file, score: Math.round(score * 1000) / 1000 });
        a.issues.push(`high similarity with ${b.file} (${score.toFixed(2)})`);
        b.issues.push(`high similarity with ${a.file} (${score.toFixed(2)})`);
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
    max_headings: maxHeadings,
    max_similarity: similarityThreshold,
    duplicates,
    flagged_files: flagged.map((i) => ({
      file: i.file,
      words: i.words,
      headings: i.headings,
      category: i.category,
      issues: i.issues,
    })),
  };

  mkdirSync(REPORTS_DIR, { recursive: true });
  writeFileSync(join(REPORTS_DIR, 'kb-modularity.json'), JSON.stringify(result, null, 2));

  const md = [
    '# KB Modularity Audit',
    '',
    `- Generated: ${result.generated}`,
    `- Total: ${result.total}`,
    `- Flagged: ${result.flagged}`,
    '',
    '## Settings',
    '',
    `- max_words: ${maxWords}`,
    `- max_headings: ${maxHeadings}`,
    `- max_similarity: ${similarityThreshold}`,
    '',
    '## Flagged files',
    '',
    ...flagged.map((i) => [
      `### ${i.file}`,
      '',
      ...i.issues.map((issue) => `- ${issue}`),
      '',
    ].join('\n')),
    ...(duplicates.length ? [
      '## High similarity pairs',
      '',
      ...duplicates.map((d) => `- ${d.a} <-> ${d.b} (${d.score})`),
    ] : []),
  ].join('\n');
  writeFileSync(join(REPORTS_DIR, 'kb-modularity.md'), md);

  console.log(JSON.stringify(result, null, 2));
}

main();
