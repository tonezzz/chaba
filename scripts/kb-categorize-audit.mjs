#!/usr/bin/env node
/*
 * Audit KB entry categories and report non-standard or missing ones.
 * Proposes a mapping to the 5 core categories.
 */
import { readFileSync, readdirSync, writeFileSync } from 'fs';
import { join } from 'path';

const KB_DIR = '/home/tony/CascadeProjects/chaba/docs/kb';
const CORE_CATEGORIES = ['operations', 'development', 'architecture', 'troubleshooting', 'implementation', 'features', 'system'];

const SUGGESTED_MAP = {
  'operations': 'operations',
  'ops': 'operations',
  'infrastructure': 'operations',
  'system': 'operations',
  'devops': 'operations',
  'development': 'development',
  'dev': 'development',
  'coding': 'development',
  'architecture': 'architecture',
  'design': 'architecture',
  'assessment': 'architecture',
  'troubleshooting': 'troubleshooting',
  'debugging': 'troubleshooting',
  'issue': 'troubleshooting',
  'incident': 'troubleshooting',
  'implementation': 'implementation',
  'feature': 'implementation',
  'testing': 'implementation',
  'meta': 'operations',
  'remote-access': 'operations',
  'hardware': 'troubleshooting',
  'missing': null,
  '': null,
};

function inferCategory(text) {
  const lower = text.toLowerCase();
  for (const [keyword, category] of Object.entries(SUGGESTED_MAP)) {
    if (lower.includes(keyword)) return category;
  }
  return null;
}

function main() {
  const files = readdirSync(KB_DIR).filter(f => f.endsWith('.md'));
  const report = [];
  let nonStandard = 0;

  for (const file of files) {
    const content = readFileSync(join(KB_DIR, file), 'utf8');
    const match = content.match(/^category:\s*(.+)$/m);
    const category = match ? match[1].trim() : 'missing';
    const isCore = CORE_CATEGORIES.includes(category);
    if (!isCore) {
      nonStandard++;
      const suggestion = SUGGESTED_MAP[category] || inferCategory(content);
      report.push(`- ‘${file}’: category=${category} -> suggest ${suggestion || 'manual review'}`);
    }
  }

  const output = `# KB Categorization Audit\n\nGenerated: ${new Date().toISOString().split('T')[0]}\n\nCore categories: ${CORE_CATEGORIES.join(', ')}\n\nNon-standard or missing categories: ${nonStandard}\n\n${report.join('\n') || 'All KB entries use core categories.'}\n`;
  writeFileSync('/home/tony/CascadeProjects/chaba/reports/KB_CATEGORIZATION_REPORT.md', output, 'utf8');
  console.log(`Non-standard/missing: ${nonStandard}`);
  console.log('Wrote reports/KB_CATEGORIZATION_REPORT.md');
}

main();
