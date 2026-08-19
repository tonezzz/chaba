#!/usr/bin/env node

/**
 * Auto KB Creation Skill
 * 
 * Analyzes KB review sections and automatically creates knowledge base entries
 * for high-value information while checking for redundancy using MCP MDDB.
 * 
 * Note: This skill should be invoked through the skill system to access MCP tools.
 * Direct execution will use fallback local file-based redundancy checking.
 */

import { readFileSync, writeFileSync, readdirSync, existsSync, unlinkSync } from 'fs';
import { join } from 'path';

const KB_DIR = '/home/tony/CascadeProjects/chaba/docs/kb';
const LOCK_FILE = '/tmp/auto-kb.lock';
const KB_COLLECTIONS = ['chaba-development', 'chaba-features', 'chaba-operations', 'chaba-system'];

// Check if running in skill context (MCP tools available)
const HAS_MCP_TOOLS = typeof mcp_call_tool === 'function' || typeof global.mcp_call_tool === 'function';

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
 * Call MCP tool (only available when skill is invoked through skill system)
 */
async function callMCPTool(serverName, toolName, args) {
  if (HAS_MCP_TOOLS) {
    try {
      // When running in skill context, use the global mcp_call_tool function
      return await mcp_call_tool(serverName, toolName, args);
    } catch (error) {
      throw new Error(`MCP tool call failed: ${error.message}`);
    }
  } else {
    throw new Error('MCP tools not available - skill must be invoked through skill system');
  }
}

/**
 * Search existing KB entries for redundancy using MDDB semantic search
 */
async function checkRedundancy(content) {
  const similarEntries = [];
  
  if (HAS_MCP_TOOLS) {
    try {
      console.log('Checking redundancy using MDDB semantic search...');
      
      // Search across all KB collections
      for (const collection of KB_COLLECTIONS) {
        try {
          const result = await callMCPTool('mddb', 'semantic_search', {
            collection: collection,
            query: content,
            top_k: 5,
            threshold: 0.4  // Only consider results with relevance > 0.4
          });
          
          if (result.results && Array.isArray(result.results)) {
            for (const hit of result.results) {
              const relevance = hit.score || 0;
              if (relevance > 0.4) {
                similarEntries.push({
                  collection: collection,
                  key: hit.key || hit.id,
                  score: relevance,
                  relevance: relevance > 0.7 ? 'high' : 'medium',
                  title: hit.meta?.title || hit.key
                });
              }
            }
          }
        } catch (collectionError) {
          console.log(`Warning: Failed to search collection ${collection}: ${collectionError.message}`);
          // Continue with other collections
        }
      }
      
      // Sort by relevance score (highest first)
      similarEntries.sort((a, b) => b.score - a.score);
      
      return {
        hasRedundancy: similarEntries.some(e => e.relevance === 'high'),
        similarEntries,
        method: 'mddb'
      };
      
    } catch (mcpError) {
      console.log(`Warning: MDDB semantic search failed: ${mcpError.message}`);
      console.log('Falling back to local file-based redundancy check...');
      // Fall through to local file-based check
    }
  } else {
    console.log('MCP tools not available, using local file-based redundancy check...');
  }
  
  // Fallback to local file-based check
  if (!existsSync(KB_DIR)) {
    return { hasRedundancy: false, similarEntries: [], method: 'none' };
  }

  const files = readdirSync(KB_DIR).filter(f => f.endsWith('.md'));
  const contentLower = content.toLowerCase();

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
        score: overlapCount / 20, // Rough score estimation
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

/**
 * Add KB entry to MDDB
 */
async function addToMDDB(filepath, filename, content) {
  if (!HAS_MCP_TOOLS) {
    console.log('MCP tools not available, skipping MDDB indexing.');
    return { success: false, error: 'MCP tools not available' };
  }
  
  try {
    console.log('Adding KB entry to MDDB...');
    
    const KB_CATEGORIES = ['operations', 'development', 'architecture', 'troubleshooting', 'implementation'];

    // Determine category and collection from content
    const category = determineCategory(content);
    let collection = 'chaba-features'; // Default
    if (category === 'troubleshooting' || category === 'development') {
      collection = 'chaba-development';
    } else if (category === 'operations') {
      collection = 'chaba-operations';
    } else if (category === 'architecture' || category === 'implementation') {
      collection = 'chaba-system';
    }
    
    // Extract title from content (first line after #)
    const titleMatch = content.match(/^#\s+(.+)$/m);
    const title = titleMatch ? titleMatch[1] : filename.replace('.md', '');
    
    const result = await callMCPTool('mddb', 'add_document', {
      collection: collection,
      key: filename,
      lang: 'en',
      content_md: content,
      meta: {
        title: title,
        source: 'auto-kb',
        created_at: new Date().toISOString(),
        auto_generated: true
      }
    });
    
    console.log(`KB entry added to MDDB collection: ${collection}`);
    return { success: true, collection };
  } catch (mcpError) {
    console.log(`Warning: Failed to add KB entry to MDDB: ${mcpError.message}`);
    console.log('KB entry was created locally but not indexed in MDDB.');
    return { success: false, error: mcpError.message };
  }
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
      '       KB_REVIEW_CONTENT="..." node auto-kb.mjs\n' +
      '       echo "..." | node auto-kb.mjs'
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
    
    // Check redundancy (now async with MDDB)
    const redundancyCheck = await checkRedundancy(content);
    
    if (redundancyCheck.method === 'mddb') {
      console.log('Used MDDB semantic search for redundancy checking.');
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
    const entry = generateKBEntry(content, context, category);
    
    // Generate filename
    const timestamp = Date.now();
    const filename = `auto-chaba-${timestamp}.md`;
    const filepath = join(KB_DIR, filename);
    
    // Write entry
    writeFileSync(filepath, entry, 'utf8');
    
    console.log(`KB entry created: ${filename}`);
    console.log(`Location: ${filepath}`);
    
    // Add to MDDB
    const mddbResult = await addToMDDB(filepath, filename, entry);
    if (mddbResult.success) {
      console.log(`Indexed in MDDB collection: ${mddbResult.collection}`);
    }
    
    console.log('Please review and refine the entry as needed.');
  } finally {
    removeLock();
  }
}

main().catch(error => {
  console.error('Auto-kb failed:', error);
  removeLock();
  process.exit(1);
});