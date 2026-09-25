#!/usr/bin/env node

/**
 * Auto KB Creation Skill
 *
 * Analyzes KB review sections and creates knowledge base entries for
 * high-value, stabilized findings, checking for redundancy using MDDB.
 *
 * Indexing is handled by this script itself via scripts/sync-kb-to-mddb.py
 * (--missing-only), which maps the entry's category frontmatter to the
 * canonical kb-* collection. The assistant may still supply an optional
 * pre-search redundancy result via MCP_REDUNDANCY_RESULT /
 * MCP_REDUNDANCY_FILE; if omitted, a local file-overlap check is used.
 *
 * Output contract: the last stdout line is
 *   AUTO_KB_RESULT {"file":..., "collection":..., "status":..., "indexed":bool, ...}
 * When indexed=false, the file exists on disk but is NOT in MDDB yet;
 * `retry` contains the command to finish indexing. Treat that as
 * "created-but-pending", not success.
 *
 * Usage:
 *   KB_REVIEW_CONTENT="..." [KB_STATUS=verified] \
 *     [MCP_REDUNDANCY_FILE=/tmp/kb-redundancy.json] node auto-kb.mjs
 *   echo "..." | node auto-kb.mjs
 *   node auto-kb.mjs "..."
 */

import { readFileSync, writeFileSync, readdirSync, existsSync, unlinkSync, mkdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { spawnSync } from 'child_process';

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(SCRIPT_DIR, '..', '..', '..');
const KB_DIR = process.env.KB_DIR || join(REPO_ROOT, 'docs', 'kb');
const SYNC_SCRIPT = join(REPO_ROOT, 'scripts', 'sync-kb-to-mddb.py');
const LOCK_FILE = process.env.AUTO_KB_LOCK_FILE || '/home/tony/.cache/auto-kb.lock';

const VALID_STATUSES = ['draft', 'verified', 'superseded', 'archived'];

function getStatus() {
  const s = (process.env.KB_STATUS || 'draft').toLowerCase();
  return VALID_STATUSES.includes(s) ? s : 'draft';
}

function slugify(title) {
  const s = title.toLowerCase().replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '').slice(0, 50);
  return s || 'entry';
}

// KB-worthy triggers
const KB_WORTHY_TRIGGERS = [
  'bug fix', 'corruption', 'security', 'vulnerability',
  'pattern', 'workaround', 'integration', 'implementation',
  'optimization', 'performance', 'configuration',
  'encoding', 'thai', 'english', 'language',
  'root cause', 'investigation', 'resolution',
  'convention', 'template', 'best practice'
];

// Negative triggers that reject low-value or meta-only content
const KB_NEGATIVE_TRIGGERS = [
  'no kb-worthy facts', 'does not meet kb-worthy', 'not kb-worthy',
  'no new kb-worthy', 'no new kb', 'nothing to save', 'consider manual creation',
  'temporary commands', 'one-off output', 'transient',
  'trivial', 'obvious', 'personal preference'
];

// Minimum thresholds
const MIN_SENTENCES = 2;
const MIN_TECHNICAL_TERMS = 2;

const TECHNICAL_INDICATORS = [
  'error', 'bug', 'fix', 'config', 'script', 'service', 'container',
  'database', 'api', 'endpoint', 'mcp', 'ssot', 'yaml', 'json',
  'python', 'node', 'docker', 'podman', 'systemd', 'git', 'commit',
  'deploy', 'proxy', 'network', 'host', 'gpu', 'embedding'
];

/**
 * Check if auto-kb is already running (concurrency protection)
 */
function isRunning() {
  if (existsSync(LOCK_FILE)) {
    const lockTime = parseInt(readFileSync(LOCK_FILE, 'utf8'));
    const now = Date.now();
    // Lock expires after 5 minutes
    if (now - lockTime < 300000) {
      return true;
    } else {
      // Stale lock, remove it
      try {
        unlinkSync(LOCK_FILE);
      } catch (e) {
        // Ignore errors
      }
      return false;
    }
  }
  return false;
}

/**
 * Create lock file
 */
function createLock() {
  writeFileSync(LOCK_FILE, Date.now().toString(), 'utf8');
}

/**
 * Remove lock file
 */
function removeLock() {
  if (existsSync(LOCK_FILE)) {
    try {
      unlinkSync(LOCK_FILE);
    } catch (e) {
      // Ignore errors
    }
  }
}

/**
 * Check if content is KB-worthy
 */
function isKBWorthy(content) {
  const lowerContent = content.toLowerCase();

  // Reject explicit low-value signals
  for (const negative of KB_NEGATIVE_TRIGGERS) {
    if (lowerContent.includes(negative)) {
      return false;
    }
  }

  // Require at least two sentences of content
  const sentences = content.split(/[.!?]/).filter(s => s.trim().length > 3);
  if (sentences.length < MIN_SENTENCES) {
    return false;
  }

  // Require positive trigger or multiple technical terms
  const hasPositiveTrigger = KB_WORTHY_TRIGGERS.some(trigger => lowerContent.includes(trigger));
  const technicalMatches = TECHNICAL_INDICATORS.filter(term => lowerContent.includes(term));
  return hasPositiveTrigger || technicalMatches.length >= MIN_TECHNICAL_TERMS;
}

/**
 * Read combined MDDB redundancy result from env or a JSON file.
 * Expected format: an array of { collection, key, score, title }
 */
function getMcpRedundancy() {
  if (process.env.MCP_REDUNDANCY_RESULT) {
    try {
      const parsed = JSON.parse(process.env.MCP_REDUNDANCY_RESULT);
      if (Array.isArray(parsed)) {
        return parsed;
      }
    } catch (e) {
      console.log('Warning: MCP_REDUNDANCY_RESULT is not valid JSON; ignoring.');
    }
  }

  if (process.env.MCP_REDUNDANCY_FILE) {
    try {
      const data = readFileSync(process.env.MCP_REDUNDANCY_FILE, 'utf8');
      const parsed = JSON.parse(data);
      if (Array.isArray(parsed)) {
        return parsed;
      }
    } catch (e) {
      console.log(`Warning: Failed to read MCP_REDUNDANCY_FILE: ${e.message}`);
    }
  }

  return null;
}

/**
 * Map a score to a relevance label
 */
function relevanceForScore(score) {
  return score > 0.7 ? 'high' : score > 0.4 ? 'medium' : 'low';
}

/**
 * Search existing KB entries for redundancy using MDDB or local files
 */
async function checkRedundancy(content) {
  const mcpEntries = getMcpRedundancy();

  // Prefer MDDB result provided by the caller
  if (mcpEntries && mcpEntries.length > 0) {
    const similarEntries = mcpEntries
      .map(e => ({
        collection: e.collection,
        key: e.key || e.id,
        score: e.score || 0,
        title: e.title || e.key || e.id,
        relevance: e.relevance || relevanceForScore(e.score || 0),
        method: 'mcp'
      }))
      .sort((a, b) => b.score - a.score);

    return {
      hasRedundancy: similarEntries.some(e => e.relevance === 'high'),
      similarEntries,
      method: 'mcp'
    };
  }

  console.log('MCP redundancy result not available, using local file-based redundancy check...');

  // Fallback to local file-based check
  if (!existsSync(KB_DIR)) {
    return { hasRedundancy: false, similarEntries: [], method: 'fallback' };
  }

  const files = readdirSync(KB_DIR).filter(f => f.endsWith('.md'));
  const contentLower = content.toLowerCase();
  const similarEntries = [];

  for (const file of files) {
    const filePath = join(KB_DIR, file);
    const existingContent = readFileSync(filePath, 'utf8').toLowerCase();

    const words = contentLower.split(/\s+/);
    const overlapCount = words.filter(word =>
      word.length > 4 && existingContent.includes(word)
    ).length;

    if (overlapCount > 5) {
      similarEntries.push({
        file,
        overlapCount,
        score: overlapCount / 20,
        relevance: overlapCount > 10 ? 'high' : 'medium',
        method: 'fallback'
      });
    }
  }

  return {
    hasRedundancy: similarEntries.some(e => e.relevance === 'high'),
    similarEntries,
    method: 'fallback'
  };
}

/**
 * Generate KB entry from content
 */
function generateKBEntry(content, context = '', category = 'implementation', status = 'draft') {
  const timestamp = new Date().toISOString().split('T')[0];

  // Extract key information from content
  const sentences = content.split('. ').filter(s => s.trim());
  const title = sentences[0]?.substring(0, 60) || 'KB Entry';

  return `---
category: ${category}
status: ${status}
created: ${timestamp}
source: auto-kb
---

# ${title}

## What it is

${sentences[0] || 'KB entry generated from assistant response.'}

## Context/Background

Created ${timestamp} from automated KB creation workflow.

${context ? `Additional context: ${context}` : ''}

## Key Details

### Technical Details
- **Generated**: ${timestamp}
- **Source**: Automated KB creation skill
- **Category**: ${category}

### Implementation
${content}

## Related Documentation

- **[auto-chaba-creation.md](../../.windsurf/workflows/auto-chaba-creation.md)** - Automated KB creation workflow

## Tags

- **auto-generated**: Automatically created KB entry
- **${timestamp.split('-')[0]}**: Year tag
`;
}

function determineCategory(content) {
  const contentLower = content.toLowerCase();
  function has(...words) { return words.some(w => contentLower.includes(w)); }
  if (has('bug', 'fix', 'error', 'corruption')) return 'troubleshooting';
  if (has('feature', 'implementation', 'integration')) return 'implementation';
  if (has('system', 'service', 'infrastructure', 'operation', 'deployment', 'monitoring')) return 'operations';
  if (has('architecture', 'design', 'pattern', 'workflow')) return 'architecture';
  return 'implementation';
}

function getMDDBCollection(category) {
  // Canonical kb-* collections — keep in sync with scripts/sync-kb-to-mddb.py
  if (category === 'troubleshooting' || category === 'development') {
    return 'kb-development';
  }
  if (category === 'operations') {
    return 'kb-operations';
  }
  if (category === 'architecture' || category === 'implementation') {
    return 'kb-system';
  }
  return 'kb-features';
}

/**
 * Index the new entry via the canonical sync script (handles collection
 * mapping, re-homing from legacy collections, and md5 drift detection).
 */
function syncIndex() {
  if (!existsSync(SYNC_SCRIPT)) {
    return { ok: false, reason: `sync script not found: ${SYNC_SCRIPT}` };
  }
  const res = spawnSync('python3', [SYNC_SCRIPT, '--missing-only'], {
    cwd: REPO_ROOT, encoding: 'utf8', timeout: 120000,
    env: { ...process.env, KB_DIR },
  });
  if (res.error || res.status !== 0) {
    const stderr = (res.stderr || '').trim().split('\n').filter(Boolean).pop() || '';
    const detail = res.error?.message || stderr || `exit ${res.status}`;
    return { ok: false, reason: detail };
  }
  return { ok: true };
}

/**
 * Read KB review content from CLI args, env, or stdin
 */
async function getInput() {
  if (process.argv[2]) {
    return process.argv[2];
  }
  if (process.env.KB_REVIEW_CONTENT) {
    return process.env.KB_REVIEW_CONTENT;
  }
  if (process.stdin.isTTY) {
    throw new Error(
      'Usage: auto-kb.mjs <chaba-review-content> [context]\n' +
      '       KB_REVIEW_CONTENT="..." [MCP_REDUNDANCY_FILE=/tmp/kb-redundancy.json] node auto-kb.mjs\n' +
      '       echo "..." | MCP_REDUNDANCY_FILE=/tmp/kb-redundancy.json node auto-kb.mjs'
    );
  }
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString('utf8').trim();
}

/**
 * Main execution
 */
async function main() {
  // Concurrency protection
  if (isRunning()) {
    console.log('Auto-kb is already running. Skipping duplicate invocation.');
    return;
  }

  createLock();

  try {
    const content = await getInput();
    const context = process.env.KB_SESSION_CONTEXT || process.argv[3] || '';

    console.log('Analyzing KB review content...');

    // Check if KB-worthy
    if (!isKBWorthy(content)) {
      console.log('Content does not meet KB-worthy criteria.');
      console.log('Consider manual creation if this is important.');
      return;
    }

    console.log('Content is KB-worthy. Checking for redundancy...');

    // Check redundancy (now async with optional MDDB result from assistant)
    const redundancyCheck = await checkRedundancy(content);

    if (redundancyCheck.method === 'mcp') {
      console.log('Used MDDB result for redundancy checking.');
    } else {
      console.log('Used fallback local file-based redundancy checking.');
    }

    if (redundancyCheck.hasRedundancy) {
      console.log('High redundancy detected with existing entries:');
      redundancyCheck.similarEntries.forEach(entry => {
        if (entry.method === 'fallback') {
          console.log(`  - ${entry.file} (${entry.relevance} relevance, ${entry.overlapCount} overlapping words)`);
        } else {
          console.log(`  - ${entry.title} (${entry.collection}, ${entry.relevance} relevance, score: ${entry.score.toFixed(2)})`);
        }
      });
      console.log('Consider updating existing entries instead of creating new ones.');
      return;
    }

    if (redundancyCheck.similarEntries.length > 0) {
      console.log('Some similarity detected with existing entries:');
      redundancyCheck.similarEntries.forEach(entry => {
        if (entry.method === 'fallback') {
          console.log(`  - ${entry.file} (${entry.relevance} relevance, ${entry.overlapCount} overlapping words)`);
        } else {
          console.log(`  - ${entry.title} (${entry.collection}, ${entry.relevance} relevance, score: ${entry.score.toFixed(2)})`);
        }
      });
    }

    console.log('Generating KB entry...');

    // Determine category and generate entry
    const category = determineCategory(content);
    const collection = getMDDBCollection(category);
    const status = getStatus();
    const title = content.split('. ')[0]?.substring(0, 60) || 'KB Entry';
    const entry = generateKBEntry(content, context, category, status);

    // Filename: auto-kb-YYYYMMDD-<slug>.md
    const date = new Date().toISOString().slice(0, 10).replace(/-/g, '');
    const filename = `auto-kb-${date}-${slugify(title)}.md`;
    const filepath = join(KB_DIR, filename);

    mkdirSync(KB_DIR, { recursive: true });
    writeFileSync(filepath, entry, 'utf8');

    // Index immediately; if MDDB is unreachable the failure is explicit
    const index = syncIndex();
    const result = { file: filename, path: filepath, category, collection, status, indexed: index.ok };
    if (!index.ok) {
      result.pending_index = true;
      result.retry = `python3 ${SYNC_SCRIPT} --missing-only`;
      console.log(`WARNING: KB file written but NOT indexed in MDDB: ${index.reason}`);
      console.log(`Retry later with: ${result.retry}`);
    }
    console.log(`KB entry created: ${filename} (status: ${status}, indexed: ${index.ok})`);
    console.log(`AUTO_KB_RESULT ${JSON.stringify(result)}`);
  } finally {
    removeLock();
  }
}

main().catch(error => {
  console.error('Auto-kb failed:', error);
  removeLock();
  process.exit(1);
});
