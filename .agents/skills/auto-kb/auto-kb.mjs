#!/usr/bin/env node

/**
 * Auto KB Creation Skill
 * 
 * Analyzes KB review sections and automatically creates knowledge base entries
 * for high-value information while checking for redundancy.
 */

import { readFileSync, writeFileSync, readdirSync, existsSync } from 'fs';
import { join } from 'path';

const KB_DIR = '/home/tony/CascadeProjects/chaba/docs/kb';

// KB-worthy triggers
const KB_WORTHY_TRIGGERS = [
  'bug fix', 'corruption', 'security', 'vulnerability',
  'pattern', 'workaround', 'integration', 'implementation',
  'optimization', 'performance', 'configuration',
  'encoding', 'thai', 'english', 'language',
  'root cause', 'investigation', 'resolution',
  'convention', 'template', 'best practice'
];

/**
 * Check if content is KB-worthy
 */
function isKBWorthy(content) {
  const lowerContent = content.toLowerCase();
  return KB_WORTHY_TRIGGERS.some(trigger => lowerContent.includes(trigger));
}

/**
 * Search existing KB entries for redundancy
 */
function checkRedundancy(content) {
  if (!existsSync(KB_DIR)) {
    return { hasRedundancy: false, similarEntries: [] };
  }

  const files = readdirSync(KB_DIR).filter(f => f.endsWith('.md'));
  const similarEntries = [];
  const contentLower = content.toLowerCase();

  for (const file of files) {
    const filePath = join(KB_DIR, file);
    const existingContent = readFileSync(filePath, 'utf-8').toLowerCase();
    
    // Check for significant content overlap
    const words = contentLower.split(/\s+/);
    const overlapCount = words.filter(word => 
      word.length > 4 && existingContent.includes(word)
    ).length;
    
    if (overlapCount > 5) {
      similarEntries.push({
        file,
        overlapCount,
        relevance: overlapCount > 10 ? 'high' : 'medium'
      });
    }
  }

  return {
    hasRedundancy: similarEntries.some(e => e.relevance === 'high'),
    similarEntries
  };
}

/**
 * Generate KB entry from content
 */
function generateKBEntry(content, context = '') {
  const timestamp = new Date().toISOString().split('T')[0];
  
  // Extract key information from content
  const sentences = content.split('. ').filter(s => s.trim());
  const title = sentences[0]?.substring(0, 60) || 'KB Entry';
  
  return `# ${title}

## What it is

${sentences[0] || 'KB entry generated from assistant response.'}

## Context/Background

Created ${timestamp} from automated KB creation workflow.

${context ? `Additional context: ${context}` : ''}

## Key Details

### Technical Details
- **Generated**: ${timestamp}
- **Source**: Automated KB creation skill

### Implementation
${content}

## Related Documentation

- **[auto-kb-creation.md](../../.windsurf/workflows/auto-kb-creation.md)** - Automated KB creation workflow

## Tags

- **auto-generated**: Automatically created KB entry
- **${timestamp.split('-')[0]}**: Year tag
`;
}

/**
 * Main execution
 */
function main() {
  const args = process.argv.slice(2);
  if (args.length === 0) {
    console.error('Usage: auto-kb.mjs <kb-review-content> [context]');
    process.exit(1);
  }

  const content = args[0];
  const context = args[1] || '';

  console.log('Analyzing KB review content...');
  
  // Check if KB-worthy
  if (!isKBWorthy(content)) {
    console.log('Content does not meet KB-worthy criteria.');
    console.log('Consider manual creation if this is important.');
    return;
  }

  console.log('Content is KB-worthy. Checking for redundancy...');
  
  // Check redundancy
  const redundancyCheck = checkRedundancy(content);
  
  if (redundancyCheck.hasRedundancy) {
    console.log('High redundancy detected with existing entries:');
    redundancyCheck.similarEntries.forEach(entry => {
      console.log(`  - ${entry.file} (${entry.relevance} relevance, ${entry.overlapCount} overlapping words)`);
    });
    console.log('Consider updating existing entries instead of creating new ones.');
    return;
  }

  if (redundancyCheck.similarEntries.length > 0) {
    console.log('Some similarity detected with existing entries:');
    redundancyCheck.similarEntries.forEach(entry => {
      console.log(`  - ${entry.file} (${entry.relevance} relevance, ${entry.overlapCount} overlapping words)`);
    });
  }

  console.log('Generating KB entry...');
  
  // Generate entry
  const entry = generateKBEntry(content, context);
  
  // Generate filename
  const timestamp = Date.now();
  const filename = `auto-kb-${timestamp}.md`;
  const filepath = join(KB_DIR, filename);
  
  // Write entry
  writeFileSync(filepath, entry, 'utf-8');
  
  console.log(`KB entry created: ${filename}`);
  console.log(`Location: ${filepath}`);
  console.log('Please review and refine the entry as needed.');
}

main();
