#!/usr/bin/env node

/**
 * KB Standardization Script
 * 
 * Automatically adds missing standard sections to KB entries and generates appropriate tags.
 */

import { readFileSync, writeFileSync, readdirSync, existsSync, statSync } from 'fs';
import { join } from 'path';

const KB_DIR = '/home/tony/CascadeProjects/chaba-tony-dell/docs/kb';

/**
 * Extract title from KB entry
 */
function extractTitle(content) {
  const titleMatch = content.match(/^#\s+(.+)$/m);
  return titleMatch ? titleMatch[1].trim() : 'Untitled';
}

/**
 * Extract first paragraph as description
 */
function extractDescription(content) {
  const lines = content.split('\n');
  for (const line of lines) {
    if (line.trim() && !line.startsWith('#') && !line.startsWith('---')) {
      return line.trim();
    }
  }
  return 'Knowledge base entry';
}

/**
 * Generate context based on file metadata
 */
function generateContext(filePath) {
  const stats = statSync(filePath);
  const created = stats.birthtime.toISOString().split('T')[0];
  return `Created ${created} as part of Chaba infrastructure documentation.`;
}

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
    'ssot': ['ssot', 'configuration', 'infrastructure']
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
 * Add missing sections to KB entry
 */
function addMissingSections(content, filename) {
  let modified = false;
  let newContent = content;

  // Check for "What it is" section
  if (!newContent.includes('## What it is')) {
    const title = extractTitle(newContent);
    const description = extractDescription(newContent);
    const whatItIs = `## What it is\n\n${description}\n\n`;
    
    // Insert after title
    const titleIndex = newContent.indexOf('\n', newContent.indexOf('# '));
    if (titleIndex !== -1) {
      newContent = newContent.slice(0, titleIndex + 1) + whatItIs + newContent.slice(titleIndex + 1);
      modified = true;
    }
  }

  // Check for "Context/Background" section
  if (!newContent.includes('## Context/Background')) {
    const context = generateContext(join(KB_DIR, filename));
    const contextSection = `## Context/Background\n\n${context}\n\n`;
    
    // Insert after "What it is" section
    const whatItIsIndex = newContent.indexOf('## What it is');
    if (whatItIsIndex !== -1) {
      const nextSectionIndex = newContent.indexOf('\n##', whatItIsIndex + 1);
      if (nextSectionIndex !== -1) {
        newContent = newContent.slice(0, nextSectionIndex) + contextSection + newContent.slice(nextSectionIndex);
        modified = true;
      }
    }
  }

  // Check for "Tags" section
  if (!newContent.includes('## Tags')) {
    const tags = generateTags(newContent, filename);
    const tagsSection = `## Tags\n\n${tags.map(tag => `- **${tag}**: ${tag}`).join('\n')}\n`;
    
    // Add at the end
    newContent += '\n' + tagsSection;
    modified = true;
  }

  return { content: newContent, modified };
}

/**
 * Process all KB entries
 */
function processKBEntries() {
  if (!existsSync(KB_DIR)) {
    console.log('KB directory not found');
    return;
  }

  const files = readdirSync(KB_DIR).filter(f => f.endsWith('.md') && f !== '.template.md');
  let processed = 0;
  let modified = 0;

  console.log(`Processing ${files.length} KB entries...`);

  for (const file of files) {
    const filePath = join(KB_DIR, file);
    const content = readFileSync(filePath, 'utf8');
    
    const result = addMissingSections(content, file);
    
    if (result.modified) {
      writeFileSync(filePath, result.content, 'utf8');
      console.log(`✓ Modified: ${file}`);
      modified++;
    } else {
      console.log(`- Skipped: ${file} (already has standard sections)`);
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
  console.log('=== KB Standardization Script ===\n');
  processKBEntries();
  console.log('\n=== Standardization Complete ===');
}

main();