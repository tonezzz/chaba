#!/usr/bin/env node
// Import wiki SQL file into PostgreSQL using mcp-wiki's pg module

import pg from 'pg';
import fs from 'fs';
const { Pool } = pg;

const SQL_FILE = '/tmp/wiki.sql';
const DATABASE_URL = process.env.DATABASE_URL;

if (!DATABASE_URL) {
  console.error('DATABASE_URL not set');
  process.exit(1);
}

const pool = new Pool({ connectionString: DATABASE_URL });

function parseInserts(content) {
  const articles = [];
  const lines = content.split('\n');

  for (let i = 0; i < lines.length; i++) {
    if (lines[i].includes('INSERT INTO articles') && !lines[i].includes('VALUES')) {
      // Next line should be VALUES
      i++;
      if (i < lines.length && lines[i].includes('VALUES (')) {
        // Collect all lines until ON CONFLICT
        const valueLines = [lines[i]];
        i++;
        while (i < lines.length && !lines[i].includes('ON CONFLICT')) {
          valueLines.push(lines[i]);
          i++;
        }
        const valueText = valueLines.join('\n');
        const article = parseInsertValue(valueText);
        if (article) articles.push(article);
      }
    }
  }
  return articles;
}

function parseInsertValue(valueText) {
  // Remove VALUES (
  valueText = valueText.replace(/^VALUES \(/, '');

  // Find title: first '...',
  const titleMatch = valueText.match(/^'([^']+)',/);
  if (!titleMatch) return null;
  const title = titleMatch[1];

  // Get remaining after title
  let remaining = valueText.slice(titleMatch[0].length).trim();

  // Find content: next '...', before ARRAY[
  const contentMatch = remaining.match(/^'([\s\S]*?)',\s*ARRAY\[/);
  if (!contentMatch) return null;
  const content = contentMatch[1];

  // Get remaining after content
  remaining = remaining.slice(contentMatch[0].length - 'ARRAY['.length);

  // Find tags: ARRAY[...]
  const tagsMatch = remaining.match(/ARRAY\[([^\]]*)\]/);
  const tags = [];
  if (tagsMatch) {
    const tagsStr = tagsMatch[1];
    const tagMatches = tagsStr.matchAll(/'([^']*)'/g);
    for (const m of tagMatches) {
      if (m[1].trim()) tags.push(m[1].trim());
    }
  }

  // Find timestamps
  const timeMatch = remaining.match(/'(\d{4}-\d{2}-\d{2}[\s\d:\.]+)',\s*'(\d{4}-\d{2}-\d{2}[\s\d:\.]+)'/);
  const created_at = timeMatch ? timeMatch[1] : '2026-04-10 00:00:00';
  const updated_at = timeMatch ? timeMatch[2] : '2026-04-10 00:00:00';

  return { title, content, tags, created_at, updated_at };
}

async function main() {
  console.log('=== Wiki SQL Import ===\n');

  const content = fs.readFileSync(SQL_FILE, 'utf-8');
  const articles = parseInserts(content);

  console.log(`Found ${articles.length} articles to import\n`);

  if (articles.length === 0) {
    console.log('No articles found!');
    return;
  }

  console.log('Connecting to PostgreSQL...');

  let migrated = 0, skipped = 0, errors = 0;

  for (const article of articles) {
    try {
      // Check if exists
      const existing = await pool.query('SELECT 1 FROM articles WHERE title = $1', [article.title]);
      if (existing.rows.length > 0) {
        console.log(`  ⚠ Skipping (exists): ${article.title.slice(0, 50)}`);
        skipped++;
        continue;
      }

      // Insert
      await pool.query(`
        INSERT INTO articles (title, content, tags, entities, classification, created_at, updated_at)
        VALUES ($1, $2, $3, NULL, NULL, $4, $5)
      `, [article.title, article.content, article.tags, article.created_at, article.updated_at]);

      console.log(`  ✅ Migrated: ${article.title.slice(0, 50)}`);
      migrated++;
    } catch (err) {
      console.log(`  ❌ Error with '${article.title.slice(0, 30)}': ${err.message}`);
      errors++;
    }
  }

  await pool.end();

  console.log(`\n=== Import Complete ===`);
  console.log(`Migrated: ${migrated}, Skipped: ${skipped}, Errors: ${errors}`);
}

main().catch(err => {
  console.error('Import failed:', err);
  process.exit(1);
});
