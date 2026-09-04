#!/usr/bin/env node
/*
 * Scan existing auto-*.md KB entries and report/archive low-value ones.
 * Uses the same quality filter as .agents/skills/auto-kb/auto-kb.mjs.
 *
 * Default mode is report-only.
 * Pass --apply to move low-quality entries to docs/kb/archive.
 * Pass --json to also write a JSON report to reports/KB_QUALITY_AUDIT.json.
 */
import { readFileSync, readdirSync, renameSync, existsSync, mkdirSync, writeFileSync } from 'fs';
import { join, basename } from 'path';

const KB_DIR = '/home/tony/CascadeProjects/chaba-tony-dell/docs/kb';
const ARCHIVE_DIR = join(KB_DIR, 'archive');
const REPORTS_DIR = '/home/tony/CascadeProjects/chaba-tony-dell/reports';

const KB_WORTHY_TRIGGERS = [
  'bug fix', 'corruption', 'security', 'vulnerability',
  'pattern', 'workaround', 'integration', 'implementation',
  'optimization', 'performance', 'configuration',
  'encoding', 'thai', 'english', 'language',
  'root cause', 'investigation', 'resolution',
  'convention', 'template', 'best practice'
];

const KB_NEGATIVE_TRIGGERS = [
  'no kb-worthy facts', 'does not meet kb-worthy', 'not kb-worthy',
  'no new kb-worthy', 'no new kb', 'nothing to save', 'consider manual creation',
  'temporary commands', 'one-off output', 'transient',
  'trivial', 'obvious', 'personal preference'
];

const MIN_SENTENCES = 2;
const MIN_TECHNICAL_TERMS = 2;

const TECHNICAL_INDICATORS = [
  'error', 'bug', 'fix', 'config', 'script', 'service', 'container',
  'database', 'api', 'endpoint', 'mcp', 'ssot', 'yaml', 'json',
  'python', 'node', 'docker', 'podman', 'systemd', 'git', 'commit',
  'deploy', 'proxy', 'network', 'host', 'gpu', 'embedding'
];

function isKBWorthy(content) {
  const lowerContent = content.toLowerCase();
  for (const negative of KB_NEGATIVE_TRIGGERS) {
    if (lowerContent.includes(negative)) return false;
  }
  const sentences = content.split(/[.!?]/).filter(s => s.trim().length > 3);
  if (sentences.length < MIN_SENTENCES) return false;
  const hasPositiveTrigger = KB_WORTHY_TRIGGERS.some(trigger => lowerContent.includes(trigger));
  const technicalMatches = TECHNICAL_INDICATORS.filter(term => lowerContent.includes(term));
  return hasPositiveTrigger || technicalMatches.length >= MIN_TECHNICAL_TERMS;
}

function extractText(filepath) {
  const raw = readFileSync(filepath, 'utf8');
  return raw.replace(/^---[\s\S]*?---\n*/, '').trim();
}

function main() {
  const args = process.argv.slice(2);
  const apply = args.includes('--apply');
  const json = args.includes('--json');
  const mode = apply ? 'archive' : 'report-only';

  if (!existsSync(ARCHIVE_DIR)) mkdirSync(ARCHIVE_DIR, { recursive: true });
  if (!existsSync(REPORTS_DIR)) mkdirSync(REPORTS_DIR, { recursive: true });

  const files = readdirSync(KB_DIR).filter(f => f.startsWith('auto-') && f.endsWith('.md'));
  let archived = 0;
  let kept = 0;
  const report = [];
  const candidates = [];

  for (const file of files) {
    const path = join(KB_DIR, file);
    const text = extractText(path);
    const worthy = isKBWorthy(text);
    if (!worthy) {
      candidates.push(file);
      if (apply) {
        const archivePath = join(ARCHIVE_DIR, file);
        const archiveNote = `\n\n_Archived ${new Date().toISOString().split('T')[0]}: did not meet updated KB quality threshold._\n`;
        writeFileSync(path, archiveNote, { flag: 'a' });
        renameSync(path, archivePath);
        archived++;
      }
      report.push(`archive candidate: ${file}`);
    } else {
      kept++;
      report.push(`kept: ${file}`);
    }
  }

  if (apply) {
    const log = `auto-kb quality audit: ${archived} archived, ${kept} kept\n\n${report.join('\n')}\n`;
    writeFileSync(join(ARCHIVE_DIR, 'audit.log'), log);
    console.log(log.trim());
  } else {
    const log = `auto-kb quality audit (report-only): ${candidates.length} archive candidates, ${kept} kept\n\n${report.join('\n')}\n`;
    console.log(log.trim());
  }

  if (json) {
    const result = {
      ok: true,
      mode,
      generated: new Date().toISOString(),
      total: files.length,
      kept,
      archived: apply ? archived : 0,
      candidates: apply ? [] : candidates,
    };
    writeFileSync(join(REPORTS_DIR, 'KB_QUALITY_AUDIT.json'), JSON.stringify(result, null, 2));
    console.log('Wrote reports/KB_QUALITY_AUDIT.json');
  }
}

main();
