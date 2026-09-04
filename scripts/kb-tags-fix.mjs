#!/usr/bin/env node

/**
 * KB Tags Fix Script
 * 
 * Adds tags to KB entries that have standard sections but are missing tags.
 */

import { readFileSync, writeFileSync, readdirSync, existsSync } from 'fs';
import { join } from 'path';

const KB_DIR = '/home/tony/CascadeProjects/chaba-tony-dell/docs/kb';

/**
 * Generate tags based on content
 */
function generateTags(content, filename) {
  const tags = new Set();
  const lowerContent = content.toLowerCase();
  const lowerFilename = filename.toLowerCase();

  // Topic-based tags
  const topicTags = {
    'docker': ['docker', 'containers', 'containerization'],
    'gpu': ['gpu', 'nvidia', 'cuda', 'ml', 'ai'],
    'yomi': ['yomi', 'line', 'messaging', 'conversations'],
    'api': ['api', 'rest', 'http', 'web'],
    'database': ['database', 'postgres', 'redis', 'mongodb', 'sql'],
    'monitoring': ['monitoring', 'health', 'metrics', 'logging'],
    'security': ['security', 'auth', 'encryption', 'ssl'],
    'deployment': ['deployment', 'ci', 'cd', 'docker'],
    'performance': ['performance', 'optimization', 'caching'],
    'testing': ['testing', 'e2e', 'automation'],
    'documentation': ['documentation', 'kb', 'knowledge-base'],
    'workflow': ['workflow', 'automation', 'mcp'],
    'h3': ['h3', 'gizmo', 'thailand'],
    'carplay': ['carplay', 'apple', 'automotive'],
    'trading': ['trading', 'finance', 'api'],
    'weaviate': ['weaviate', 'vector', 'database'],
    'ssot': ['ssot', 'configuration', 'infrastructure'],
    'worktree': ['worktree', 'git', 'branching'],
    'raceman': ['raceman', 'php', 'worktree'],
    'playwright': ['playwright', 'testing', 'automation'],
    'playlive': ['playlive', 'mcp', 'browser'],
    'hibernation': ['hibernation', 'power', 'system'],
    'language': ['language', 'detection', 'nlp'],
    'gemini': ['gemini', 'ai', 'google'],
    'commercial': ['commercial', 'filtering', 'content'],
    'thailand': ['thailand', 'timezone', 'locale'],
    'yaml': ['yaml', 'configuration', 'syntax'],
    'e2e': ['e2e', 'testing', 'automation'],
    'security': ['security', 'scanning', 'vulnerability']
  };

  // Add tags based on content
  for (const [topic, keywords] of Object.entries(topicTags)) {
    if (lowerContent.includes(topic) || lowerFilename.includes(topic)) {
      keywords.forEach(tag => tags.add(tag));
    }
  }

  // Add year tag
  const year = new Date().getFullYear().toString();
  tags.add(year);

  return Array.from(tags);
}

/**
 * Add tags to KB entry
 */
function addTags(content, filename) {
  if (content.includes('## Tags')) {
    // Extract existing tags section
    const tagsIndex = content.indexOf('## Tags');
    const afterTags = content.slice(tagsIndex);
    
    // Check if tags section has content
    const lines = afterTags.split('\n');
    const hasTags = lines.some(line => line.includes('- **') && line.includes('**:'));
    
    if (hasTags) {
      return { content, modified: false };
    }
    
    // Generate new tags
    const tags = generateTags(content, filename);
    const tagsSection = `## Tags\n\n${tags.map(tag => `- **${tag}**: ${tag}`).join('\n')}\n`;
    
    // Replace empty tags section
    const newContent = content.slice(0, tagsIndex) + tagsSection;
    return { content: newContent, modified: true };
  }
  
  // No tags section at all
  const tags = generateTags(content, filename);
  const tagsSection = `\n## Tags\n\n${tags.map(tag => `- **${tag}**: ${tag}`).join('\n')}\n`;
  return { content: content + tagsSection, modified: true };
}

/**
 * Process KB entries without tags
 */
function processKBEntries() {
  if (!existsSync(KB_DIR)) {
    console.log('KB directory not found');
    return;
  }

  const files = readdirSync(KB_DIR).filter(f => f.endsWith('.md') && f !== '.template.md');
  let processed = 0;
  let modified = 0;

  console.log(`Processing ${files.length} KB entries for missing tags...`);

  for (const file of files) {
    const filePath = join(KB_DIR, file);
    const content = readFileSync(filePath, 'utf8');
    
    const result = addTags(content, file);
    
    if (result.modified) {
      writeFileSync(filePath, result.content, 'utf8');
      console.log(`✓ Added tags: ${file}`);
      modified++;
    } else {
      console.log(`- Skipped: ${file} (already has tags)`);
    }
    
    processed++;
  }

  console.log(`\nProcessed: ${processed} entries`);
  console.log(`Modified: ${modified} entries`);
  console.log(`Skipped: ${processed - modified} entries`);
}

/**
 * Main execution
 */
function main() {
  console.log('=== KB Tags Fix Script ===\n');
  processKBEntries();
  console.log('\n=== Tags Fix Complete ===');
}

main();