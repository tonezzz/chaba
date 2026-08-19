#!/usr/bin/env node

/**
 * Auto KB Creation Skill
 *
 * Analyzes KB review sections and automatically creates knowledge base entries
 * for high-value information while checking for redundancy using MDDB.
 *
 * MDDB access is intentionally not performed inside this Node process, because
 * mcp_call_tool is a Devin assistant tool and is not available as a Node
 * global. The caller (assistant) is expected to:
 *   1. Call mcp_call_tool mddb semantic_search for relevant collections.
 *   2. Pass the combined result as MCP_REDUNDANCY_RESULT (JSON string) or
 *      MCP_REDUNDANCY_FILE (path to a JSON file).
 *   3. After a local KB file is created, call mcp_call_tool mddb add_document
 *      to index it.
 *
 * Usage:
 *   KB_REVIEW_CONTENT="..." [MCP_REDUNDANCY_FILE=/tmp/kb-redundancy.json] node auto-kb.mjs
 *   echo "..." | MCP_REDUNDANCY_FILE=/tmp/kb-redundancy.json node auto-kb.mjs
 *   node auto-kb.mjs "..."
 */

import { readFileSync, writeFileSync, readdirSync, existsSync, unlinkSync } from 'fs';
import { join } from 'path';

const KB_DIR = process.env.KB_DIR || '/home/tony/CascadeProjects/chaba/docs/kb';
const LOCK_FILE = '/tmp/auto-kb.lock';

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
function generateKBEntry(content, context = '', category = 'implementation') {
  const timestamp = new Date().toISOString().split('T')[0];

  // Extract key information from content
  const sentences = content.split('. ').filter(s => s.trim());
  const title = sentences[0]?.substring(0, 60) || 'KB Entry';

  return `---
category: ${category}
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
  if (category === 'troubleshooting' || category === 'development') {
    return 'chaba-development';
  }
  if (category === 'operations') {
    return 'chaba-operations';
  }
  if (category === 'architecture' || category === 'implementation') {
    return 'chaba-system';
  }
  return 'chaba-features';
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
    const entry = generateKBEntry(content, context, category);

    // Generate filename
    const timestamp = Date.now();
    const filename = `auto-chaba-${timestamp}.md`;
    const filepath = join(KB_DIR, filename);

    // Ensure directory exists
    if (!existsSync(KB_DIR)) {
      // noop: let writeFileSync fail if needed, or create with mkdirSync?
      // Keep minimal: original did not create KB_DIR.
    }

    // Write entry
    writeFileSync(filepath, entry, 'utf8');

    console.log(`KB entry created: ${filename}`);
    console.log(`Location: ${filepath}`);
    console.log(`Category: ${category}`);
    console.log(`MDDB collection: ${collection}`);
    console.log('To index in MDDB, call:');
    console.log(`  mcp_call_tool mddb add_document collection=${collection} key=${filename} lang=en content_md=<entry> meta={title:"...",source:"auto-kb",auto_generated:true}`);
  } finally {
    removeLock();
  }
}

main().catch(error => {
  console.error('Auto-kb failed:', error);
  removeLock();
  process.exit(1);
});
