#!/usr/bin/env node

import { readFileSync, existsSync, writeFileSync } from 'fs';
import { execSync } from 'child_process';

const SSOT_PATH = '/home/tony/CascadeProjects/chaba-tony-dell/docs/ssot/ssot.improvements.yml';

// Parse command line arguments
const args = process.argv.slice(2);
const improvementLabel = args[0];
const commitMessage = args[1] || '';

if (!improvementLabel) {
  console.error('Usage: node link-improvement-to-git.mjs <improvement-label> [commit-message]');
  console.error('Example: node link-improvement-to-git.mjs "Docker Compose Configuration Fix" "Remove obsolete version attribute"');
  process.exit(1);
}

console.log(`Linking improvement "${improvementLabel}" to git commit`);

// Get current git info
try {
  const commit = execSync('git rev-parse HEAD', { encoding: 'utf8' }).trim();
  const branch = execSync('git rev-parse --abbrev-ref HEAD', { encoding: 'utf8' }).trim();
  const shortCommit = commit.substring(0, 8);
  
  console.log(`Current commit: ${shortCommit}`);
  console.log(`Current branch: ${branch}`);
  
  // Load SSOT file
  if (!existsSync(SSOT_PATH)) {
    console.error('SSOT improvements file not found');
    process.exit(1);
  }
  
  const ssotContent = readFileSync(SSOT_PATH, 'utf8');
  const lines = ssotContent.split('\n');
  
  // Find the improvement
  let improvementFound = false;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].includes(`label: ${improvementLabel}`)) {
      improvementFound = true;
      
      // Check if git info already exists
      let hasGitInfo = false;
      for (let j = i + 1; j < Math.min(i + 15, lines.length); j++) {
        if (lines[j].includes('git_commit:')) {
          hasGitInfo = true;
          break;
        }
        if (lines[j].trim().startsWith('- label:')) {
          break;
        }
      }
      
      if (hasGitInfo) {
        console.log('Improvement already has git information');
        process.exit(0);
      }
      
      // Add git info after the improvement
      const gitLines = [
        `    git_commit: ${commit}`,
        `    git_branch: ${branch}`,
        `    git_short_commit: ${shortCommit}`
      ];
      
      if (commitMessage) {
        gitLines.push(`    git_commit_message: ${commitMessage}`);
      }
      
      // Insert git lines
      let insertIndex = i + 1;
      while (insertIndex < lines.length && !lines[insertIndex].trim().startsWith('- label:') && insertIndex < i + 15) {
        insertIndex++;
      }
      
      lines.splice(insertIndex, 0, ...gitLines);
      
      // Write back to file
      writeFileSync(SSOT_PATH, lines.join('\n'));
      
      console.log(`✅ Successfully linked improvement to git commit ${shortCommit}`);
      console.log(`Branch: ${branch}`);
      if (commitMessage) {
        console.log(`Commit message: ${commitMessage}`);
      }
      
      break;
    }
  }
  
  if (!improvementFound) {
    console.error(`Improvement "${improvementLabel}" not found in SSOT`);
    process.exit(1);
  }
  
} catch (error) {
  console.error(`Error: ${error.message}`);
  
  if (error.message.includes('git')) {
    console.error('Git command failed. Make sure you are in a git repository.');
  }
  
  process.exit(1);
}