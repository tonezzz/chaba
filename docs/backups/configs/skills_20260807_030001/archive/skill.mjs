#!/usr/bin/env node

/**
 * Global Archive Session Skill
 * 
 * Project-agnostic session archiving with timestamp-based filenames.
 * Auto-detects project structure and creates sessions directory as needed.
 * Usage: node skill.mjs <project> <title> [summary]
 *        Or run interactively without arguments
 */

import fs from 'fs';
import path from 'path';
import readline from 'readline';

async function detectProjectStructure(cwd) {
  const possiblePaths = [
    { type: 'chaba', ssot: 'docs/overview', sessions: 'docs/overview/sessions' },
    { type: 'generic', ssot: '.sessions', sessions: '.sessions' },
    { type: 'fallback', ssot: 'docs/overview', sessions: 'docs/overview/sessions' }
  ];

  for (const { type, ssot, sessions } of possiblePaths) {
    const ssotPath = path.join(cwd, ssot);
    if (fs.existsSync(ssotPath)) {
      return { type, ssotDir: ssotPath, sessionsDir: path.join(cwd, sessions) };
    }
  }

  const sessionsDir = path.join(cwd, '.sessions');
  fs.mkdirSync(sessionsDir, { recursive: true });
  return { type: 'generic', ssotDir: null, sessionsDir };
}

async function archiveSession() {
  let projectRoot = process.cwd();
  const args = process.argv.slice(2);

  if (args[0] && fs.existsSync(args[0])) {
    projectRoot = args[0];
    args.shift();
  }

  console.log('📦 Global session archiving...');
  console.log(`   Project root: ${projectRoot}`);

  const { type, ssotDir, sessionsDir } = await detectProjectStructure(projectRoot);
  console.log(`   Project type: ${type}`);
  console.log(`   Sessions dir: ${sessionsDir}`);

  const now = new Date();
  const dateStr = now.toISOString().split('T')[0];
  const timestamp = now.toISOString().replace(/[:.]/g, '-').slice(0, -5);

  let project, title, summary;

  if (args.length >= 2) {
    project = args[0];
    title = args[1];
    summary = args[2] || 'No summary';
    console.log(`   Project: ${project}`);
    console.log(`   Title: ${title}`);
    console.log(`   Summary: ${summary}`);
  } else {
    console.log('\n📝 Session Details:');
    console.log('Enter session details (press Enter to skip optional fields):\n');

    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout
    });

    const question = (prompt) => new Promise(resolve => {
      rl.question(prompt, resolve);
    });

    const dirName = path.basename(projectRoot);
    project = await question(`Project name [${dirName}]: `) || dirName;
    title = await question('Session title: ');
    summary = await question('Summary (one line): ');

    rl.close();
  }

  if (!project) {
    console.error('❌ Project name is required');
    process.exit(1);
  }

  if (!title) {
    console.error('❌ Session title is required');
    process.exit(1);
  }

  const projectSessionsDir = path.join(sessionsDir, project);
  if (!fs.existsSync(projectSessionsDir)) {
    fs.mkdirSync(projectSessionsDir, { recursive: true });
    console.log(`   Created: ${projectSessionsDir}`);
  }

  const sessionFile = `${timestamp}.yml`;
  const filepath = path.join(projectSessionsDir, sessionFile);

  let content = `title: ${title}\n`;
  content += `date: ${dateStr}\n`;
  content += `timestamp: ${now.toISOString()}\n`;
  content += `summary: '${summary}'\n`;
  content += `project: ${project}\n`;
  content += `project_root: ${projectRoot}\n`;
  content += `project_type: ${type}\n`;
  content += `sections:\n`;
  content += `  - title: Details\n`;
  content += `    icon: 📝\n`;
  content += `    layout: list\n`;
  content += `    items:\n`;
  content += `      - label: Summary\n`;
  content += `        text: '${summary}'\n`;
  content += `      - label: Project\n`;
  content += `        text: '${project}'\n`;
  content += `      - label: Date\n`;
  content += `        text: '${dateStr}'\n`;
  content += `      - label: Project Root\n`;
  content += `        text: '${projectRoot}'\n`;

  fs.writeFileSync(filepath, content);

  console.log(`\n✅ Session archived to: ${filepath}`);
  console.log(`   Project: ${project}`);
  console.log(`   Date: ${dateStr}`);
  console.log(`   Title: ${title}`);
  console.log(`   Timestamp: ${timestamp}`);

  return { success: true, filepath, project, type };
}

archiveSession()
  .then(result => {
    process.exit(0);
  })
  .catch(error => {
    console.error(`❌ Archive failed: ${error.message}`);
    console.error(error.stack);
    process.exit(1);
  });
