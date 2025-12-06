#!/usr/bin/env node
const fs = require('fs');
const fsp = fs.promises;
const path = require('path');

const siteRoot = path.join(__dirname, '..');
const sourceDir = path.join(siteRoot, 'test', 'agents');
const targetDir = path.join(siteRoot, 'www', 'test', 'agents');

const log = (message) => {
  process.stdout.write(`[sync-agents-ui] ${message}\n`);
};

const ensureSourceExists = async () => {
  try {
    const stats = await fsp.stat(sourceDir);
    if (!stats.isDirectory()) {
      throw new Error('source is not a directory');
    }
  } catch (error) {
    throw new Error(`Source directory missing (${sourceDir}): ${error.message}`);
  }
};

const copyRecursive = async (src, dest) => {
  const stats = await fsp.stat(src);
  if (stats.isDirectory()) {
    await fsp.mkdir(dest, { recursive: true });
    const entries = await fsp.readdir(src);
    for (const entry of entries) {
      if (entry === '.DS_Store') continue;
      await copyRecursive(path.join(src, entry), path.join(dest, entry));
    }
    return;
  }
  await fsp.mkdir(path.dirname(dest), { recursive: true });
  await fsp.copyFile(src, dest);
};

const run = async () => {
  await ensureSourceExists();
  await fsp.rm(targetDir, { recursive: true, force: true });
  await fsp.mkdir(targetDir, { recursive: true });
  await copyRecursive(sourceDir, targetDir);
  log(`Copied UI from ${sourceDir} -> ${targetDir}`);
};

run().catch((error) => {
  console.error('[sync-agents-ui] failed:', error);
  process.exitCode = 1;
});
