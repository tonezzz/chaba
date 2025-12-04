#!/usr/bin/env node
import fs from 'fs';
import path from 'path';

const root = process.argv[2] || path.resolve('knowledge', 'docs');
const query = (process.argv[3] || '').toLowerCase();
if (!query) {
  console.error('Usage: kb-search <docsDir> <query>');
  process.exit(1);
}

const matches = [];
const walk = (dir) => {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walk(fullPath);
    } else if (entry.isFile()) {
      const text = fs.readFileSync(fullPath, 'utf8');
      if (text.toLowerCase().includes(query)) {
        matches.push({ file: fullPath, preview: text.slice(0, 200) });
      }
    }
  }
};

walk(root);
console.log(JSON.stringify({ query, matches }, null, 2));
