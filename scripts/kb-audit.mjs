#!/usr/bin/env node

/**
 * KB Audit Tool
 * 
 * Audits the knowledge base for coverage gaps, missing entries, and quality issues.
 * Compares current KB entries with git history and project documentation.
 */

import { readFileSync, writeFileSync, readdirSync, existsSync, statSync } from 'fs';
import { join } from 'path';
import { execSync } from 'child_process';

const KB_DIR = '/home/tony/CascadeProjects/chaba-tony-dell/docs/kb';
const PROJECT_DIR = '/home/tony/CascadeProjects/chaba-tony-dell';

/**
 * Get all KB entries with metadata
 */
function getKBEntries() {
  if (!existsSync(KB_DIR)) {
    return [];
  }

  const files = readdirSync(KB_DIR).filter(f => f.endsWith('.md') && f !== '.template.md');
  const entries = [];

  for (const file of files) {
    const filePath = join(KB_DIR, file);
    const stats = statSync(filePath);
    const content = readFileSync(filePath, 'utf8');
    
    // Extract title and tags
    const titleMatch = content.match(/^#\s+(.+)$/m);
    const tagsMatch = content.match(/## Tags\s*\n([\s\S]+?)(?=\n##|$)/);
    
    const tags = [];
    if (tagsMatch) {
      const tagLines = tagsMatch[1].split('\n').filter(line => line.trim());
      tagLines.forEach(line => {
        const match = line.match(/\*\*([^*]+)\*\*/);
        if (match) tags.push(match[1]);
      });
    }

    entries.push({
      file,
      title: titleMatch ? titleMatch[1].trim() : file,
      created: stats.birthtime,
      modified: stats.mtime,
      size: stats.size,
      tags,
      wordCount: content.split(/\s+/).length
    });
  }

  return entries.sort((a, b) => b.modified - a.modified);
}

/**
 * Get git history for KB entries
 */
function getGitHistory() {
  try {
    const gitLog = execSync('git log --name-only --pretty=format:"%H|%ai|%s" -- docs/kb/', {
      cwd: PROJECT_DIR,
      encoding: 'utf8'
    });

    const commits = [];
    const lines = gitLog.split('\n');
    let currentCommit = null;

    for (const line of lines) {
      if (line.includes('|')) {
        if (currentCommit) {
          commits.push(currentCommit);
        }
        const [hash, date, message] = line.split('|');
        currentCommit = { hash, date, message, files: [] };
      } else if (line.trim() && currentCommit) {
        currentCommit.files.push(line.trim());
      }
    }

    if (currentCommit) {
      commits.push(currentCommit);
    }

    return commits;
  } catch (error) {
    console.log('Git history not available:', error.message);
    return [];
  }
}

/**
 * Search for terms that should have KB entries
 */
function searchMissingTopics() {
  const importantTerms = [
    'podman', 'container', 'docker', 'kubernetes',
    'authentication', 'auth', 'jwt', 'oauth',
    'database', 'postgres', 'redis', 'mongodb',
    'api', 'rest', 'graphql', 'websocket',
    'security', 'encryption', 'ssl', 'tls',
    'monitoring', 'logging', 'metrics',
    'deployment', 'ci/cd', 'testing',
    'performance', 'optimization', 'caching',
    'migration', 'backup', 'disaster recovery'
  ];

  const missingTopics = [];
  const kbContent = readdirSync(KB_DIR)
    .filter(f => f.endsWith('.md'))
    .map(f => readFileSync(join(KB_DIR, f), 'utf8').toLowerCase())
    .join('\n');

  for (const term of importantTerms) {
    if (!kbContent.includes(term)) {
      missingTopics.push(term);
    }
  }

  return missingTopics;
}

/**
 * Check for outdated entries
 */
function checkOutdatedEntries(entries) {
  const now = new Date();
  const sixMonthsAgo = new Date(now.getTime() - 6 * 30 * 24 * 60 * 60 * 1000);
  
  return entries.filter(entry => entry.modified < sixMonthsAgo);
}

/**
 * Check for quality issues
 */
function checkQualityIssues(entries) {
  const issues = [];

  for (const entry of entries) {
    const filePath = join(KB_DIR, entry.file);
    const content = readFileSync(filePath, 'utf8');

    // Check for missing sections
    if (!content.includes('## What it is')) {
      issues.push({ file: entry.file, issue: 'Missing "What it is" section' });
    }
    if (!content.includes('## Context/Background')) {
      issues.push({ file: entry.file, issue: 'Missing "Context/Background" section' });
    }
    if (!content.includes('## Tags')) {
      issues.push({ file: entry.file, issue: 'Missing "Tags" section' });
    }

    // Check for very short entries
    if (entry.wordCount < 100) {
      issues.push({ file: entry.file, issue: 'Very short entry (<100 words)' });
    }

    // Check for entries without tags
    if (entry.tags.length === 0) {
      issues.push({ file: entry.file, issue: 'No tags defined' });
    }
  }

  return issues;
}

/**
 * Generate audit report
 */
function generateReport() {
  console.log('=== KB Audit Report ===\n');
  console.log(`Generated: ${new Date().toISOString()}\n`);

  const entries = getKBEntries();
  console.log(`Total KB entries: ${entries.length}\n`);

  // Recent entries
  console.log('=== Recent Entries (Last 30 days) ===');
  const thirtyDaysAgo = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000);
  const recentEntries = entries.filter(e => e.modified > thirtyDaysAgo);
  recentEntries.forEach(entry => {
    console.log(`- ${entry.file} (${entry.modified.toISOString().split('T')[0]})`);
  });
  console.log(`\nRecent entries: ${recentEntries.length}\n`);

  // Outdated entries
  console.log('=== Potentially Outdated Entries (>6 months) ===');
  const outdatedEntries = checkOutdatedEntries(entries);
  outdatedEntries.forEach(entry => {
    console.log(`- ${entry.file} (last modified: ${entry.modified.toISOString().split('T')[0]})`);
  });
  console.log(`\nOutdated entries: ${outdatedEntries.length}\n`);

  // Quality issues
  console.log('=== Quality Issues ===');
  const qualityIssues = checkQualityIssues(entries);
  qualityIssues.forEach(issue => {
    console.log(`- ${issue.file}: ${issue.issue}`);
  });
  console.log(`\nQuality issues: ${qualityIssues.length}\n`);

  // Missing topics
  console.log('=== Potentially Missing Topics ===');
  const missingTopics = searchMissingTopics();
  missingTopics.forEach(topic => {
    console.log(`- ${topic}`);
  });
  console.log(`\nMissing topics: ${missingTopics.length}\n`);

  // Git history
  console.log('=== Recent KB Commits ===');
  const gitHistory = getGitHistory();
  gitHistory.slice(0, 5).forEach(commit => {
    console.log(`- ${commit.date.split('T')[0]}: ${commit.message}`);
    commit.files.forEach(file => {
      console.log(`  ${file}`);
    });
  });
  console.log(`\nTotal KB commits: ${gitHistory.length}\n`);

  // Summary
  console.log('=== Summary ===');
  console.log(`Total entries: ${entries.length}`);
  console.log(`Recent entries: ${recentEntries.length}`);
  console.log(`Outdated entries: ${outdatedEntries.length}`);
  console.log(`Quality issues: ${qualityIssues.length}`);
  console.log(`Missing topics: ${missingTopics.length}`);
  console.log(`Git commits: ${gitHistory.length}`);
  console.log();

  // Recommendations
  console.log('=== Recommendations ===');
  if (outdatedEntries.length > 0) {
    console.log('- Review and update outdated entries');
  }
  if (qualityIssues.length > 0) {
    console.log('- Fix quality issues in KB entries');
  }
  if (missingTopics.length > 0) {
    console.log('- Consider creating KB entries for missing topics');
  }
  if (recentEntries.length === 0) {
    console.log('- KB appears inactive - consider adding new entries');
  }
  console.log();

  return {
    entries,
    recentEntries,
    outdatedEntries,
    qualityIssues,
    missingTopics,
    gitHistory
  };
}

/**
 * Main execution
 */
function main() {
  const args = process.argv.slice(2);
  const report = generateReport();

  if (args.includes('--json')) {
    console.log(JSON.stringify(report, null, 2));
  }

  if (args.includes('--save')) {
    const reportPath = join(PROJECT_DIR, 'reports', 'kb-audit.json');
    const reportsDir = join(PROJECT_DIR, 'reports');
    
    if (!existsSync(reportsDir)) {
      // Would need to create directory
    }
    
    writeFileSync(reportPath, JSON.stringify(report, null, 2), 'utf8');
    console.log(`Report saved to: ${reportPath}`);
  }
}

main();