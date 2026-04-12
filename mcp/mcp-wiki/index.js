import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';
import sqlite3 from 'sqlite3';
import pg from 'pg';
import { z } from 'zod';
import { zodToJsonSchema } from 'zod-to-json-schema';
import fs from 'fs';
import path from 'path';
import express from 'express';

const { Pool } = pg;

// Database configuration
const USE_POSTGRES = process.env.WIKI_USE_POSTGRES === '1' || process.env.DATABASE_URL !== undefined;
const DATABASE_URL = process.env.DATABASE_URL || 'postgresql://chaba:changeme@idc1.surf-thailand.com:5432/chaba';
const DB_PATH = process.env.WIKI_DB_PATH || '/data/wiki.db';
const DATA_DIR = path.dirname(DB_PATH);
const HTTP_PORT = process.env.WIKI_HTTP_PORT || 8080;

let db;
let pgPool;

async function initDatabase() {
  if (USE_POSTGRES) {
    // PostgreSQL mode
    pgPool = new Pool({
      connectionString: DATABASE_URL,
    });
    
    // Initialize PostgreSQL tables
    await pgPool.query(`
      CREATE TABLE IF NOT EXISTS articles (
        id SERIAL PRIMARY KEY,
        title VARCHAR(255) UNIQUE NOT NULL,
        content TEXT NOT NULL,
        tags TEXT[],
        entities JSONB,
        classification VARCHAR(100),
        metadata JSONB DEFAULT '{}',
        embedding vector(1536),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
    `);
    
    // AI enhancement queue
    await pgPool.query(`
      CREATE TABLE IF NOT EXISTS article_ai_queue (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        article_id INTEGER REFERENCES articles(id) ON DELETE CASCADE,
        action VARCHAR(50) NOT NULL,
        status VARCHAR(20) DEFAULT 'pending',
        result JSONB,
        error TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        processed_at TIMESTAMP
      )
    `);
    
    await pgPool.query(`
      CREATE INDEX IF NOT EXISTS idx_articles_title ON articles USING gin(to_tsvector('english', title))
    `);
    
    await pgPool.query(`
      CREATE INDEX IF NOT EXISTS idx_articles_content ON articles USING gin(to_tsvector('english', content))
    `);
    
    console.error('mcp-wiki: Using PostgreSQL database');
  } else {
    // SQLite mode
    if (!fs.existsSync(DATA_DIR)) {
      fs.mkdirSync(DATA_DIR, { recursive: true });
    }
    
    db = new sqlite3.Database(DB_PATH);
    
    // Create tables
    db.serialize(() => {
      db.run(`
        CREATE TABLE IF NOT EXISTS articles (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          title TEXT UNIQUE NOT NULL,
          content TEXT NOT NULL,
          tags TEXT,
          metadata TEXT DEFAULT '{}',
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
      `);
      
      db.run(`
        CREATE INDEX IF NOT EXISTS idx_articles_title ON articles(title)
      `);
      
      db.run(`
        CREATE INDEX IF NOT EXISTS idx_articles_tags ON articles(tags)
      `);
    });
    
    console.error('mcp-wiki: Using SQLite database at', DB_PATH);
  }
}

// Schema definitions
const SearchArticlesSchema = z.object({
  query: z.string(),
  limit: z.number().optional().default(10)
});

const GetArticleSchema = z.object({
  title: z.string()
});

const CreateArticleSchema = z.object({
  title: z.string(),
  content: z.string(),
  tags: z.array(z.string()).optional()
});

const UpdateArticleSchema = z.object({
  title: z.string(),
  content: z.string(),
  tags: z.array(z.string()).optional()
});

const ListArticlesSchema = z.object({
  limit: z.number().optional().default(20),
  offset: z.number().optional().default(0)
});

// Database helpers - support both SQLite and PostgreSQL
async function searchArticles(query, limit) {
  if (USE_POSTGRES) {
    const result = await pgPool.query(`
      SELECT title, tags, created_at, updated_at,
             left(content, 200) as snippet
      FROM articles
      WHERE to_tsvector('english', title || ' ' || content) @@ plainto_tsquery('english', $1)
      ORDER BY ts_rank(to_tsvector('english', title || ' ' || content), plainto_tsquery('english', $1)) DESC,
               updated_at DESC
      LIMIT $2
    `, [query, limit]);
    return result.rows;
  } else {
    // SQLite fallback
    return new Promise((resolve, reject) => {
      const fallbackSql = `
        SELECT title, tags, created_at, updated_at,
               substr(content, 1, 200) as snippet
        FROM articles
        WHERE title LIKE ? OR content LIKE ?
        ORDER BY updated_at DESC
        LIMIT ?
      `;
      const pattern = `%${query}%`;
      db.all(fallbackSql, [pattern, pattern, limit], (err, rows) => {
        if (err) reject(err);
        else resolve(rows);
      });
    });
  }
}

async function getArticle(title) {
  if (USE_POSTGRES) {
    const result = await pgPool.query(
      'SELECT * FROM articles WHERE title = $1',
      [title]
    );
    return result.rows[0] || null;
  } else {
    // SQLite
    return new Promise((resolve, reject) => {
      db.get(
        'SELECT * FROM articles WHERE title = ?',
        [title],
        (err, row) => {
          if (err) reject(err);
          else resolve(row || null);
        }
      );
    });
  }
}

async function createArticle(title, content, tags, entities, classification) {
  if (USE_POSTGRES) {
    try {
      const result = await pgPool.query(
        `INSERT INTO articles (title, content, tags, entities, classification) 
         VALUES ($1, $2, $3, $4, $5) RETURNING id, title`,
        [title, content, tags || [], entities ? JSON.stringify(entities) : null, classification || null]
      );
      return result.rows[0];
    } catch (err) {
      if (err.code === '23505') { // unique_violation
        throw new Error(`Article "${title}" already exists`);
      }
      throw err;
    }
  } else {
    // SQLite
    return new Promise((resolve, reject) => {
      const tagsStr = tags ? tags.join(',') : null;
      const entitiesStr = entities ? (Array.isArray(entities) ? entities.join(',') : entities) : null;
      db.run(
        `INSERT INTO articles (title, content, tags) VALUES (?, ?, ?)`,
        [title, content, tagsStr],
        function(err) {
          if (err) {
            if (err.message.includes('UNIQUE constraint failed')) {
              reject(new Error(`Article "${title}" already exists`));
            } else {
              reject(err);
            }
          } else {
            resolve({ id: this.lastID, title });
          }
        }
      );
    });
  }
}

async function updateArticle(title, content, tags) {
  if (USE_POSTGRES) {
    const result = await pgPool.query(
      `UPDATE articles SET content = $1, tags = $2, updated_at = CURRENT_TIMESTAMP 
       WHERE title = $3 RETURNING title`,
      [content, tags || [], title]
    );
    if (result.rowCount === 0) {
      throw new Error(`Article "${title}" not found`);
    }
    return { title: result.rows[0].title, updated: true };
  } else {
    // SQLite
    return new Promise((resolve, reject) => {
      const tagsStr = tags ? tags.join(',') : null;
      db.run(
        `UPDATE articles SET content = ?, tags = ?, updated_at = CURRENT_TIMESTAMP WHERE title = ?`,
        [content, tagsStr, title],
        function(err) {
          if (err) reject(err);
          else if (this.changes === 0) reject(new Error(`Article "${title}" not found`));
          else resolve({ title, updated: true });
        }
      );
    });
  }
}

// Format date to Bangkok time (UTC+7), short format
function formatDate(dateString) {
  if (!dateString) return '';
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now - date;
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);
  
  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays === 1) return 'yesterday';
  if (diffDays < 7) return `${diffDays}d ago`;
  
  return date.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit'
  }) + ' BKK';
}

async function listArticles(limit, offset) {
  if (USE_POSTGRES) {
    const result = await pgPool.query(
      `SELECT id, title, tags, metadata, created_at, updated_at 
       FROM articles ORDER BY updated_at DESC LIMIT $1 OFFSET $2`,
      [limit, offset]
    );
    return result.rows;
  } else {
    // SQLite
    return new Promise((resolve, reject) => {
      db.all(
        `SELECT id, title, tags, metadata, created_at, updated_at FROM articles ORDER BY updated_at DESC LIMIT ? OFFSET ?`,
        [limit, offset],
        (err, rows) => {
          if (err) reject(err);
          else resolve(rows);
        }
      );
    });
  }
}

// MCP Server
const server = new Server({ name: 'mcp-wiki', version: '1.0.0' }, {
  capabilities: { tools: {} }
});

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: 'wiki_search',
      description: 'Search articles by title or content',
      inputSchema: zodToJsonSchema(SearchArticlesSchema)
    },
    {
      name: 'wiki_get',
      description: 'Get article content by title',
      inputSchema: zodToJsonSchema(GetArticleSchema)
    },
    {
      name: 'wiki_create',
      description: 'Create new article',
      inputSchema: zodToJsonSchema(CreateArticleSchema)
    },
    {
      name: 'wiki_update',
      description: 'Update existing article',
      inputSchema: zodToJsonSchema(UpdateArticleSchema)
    },
    {
      name: 'wiki_list',
      description: 'List recent articles',
      inputSchema: zodToJsonSchema(ListArticlesSchema)
    }
  ]
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  
  try {
    switch (name) {
      case 'wiki_search': {
        const { query, limit } = SearchArticlesSchema.parse(args);
        const results = await searchArticles(query, limit);
        return {
          content: [{
            type: 'text',
            text: JSON.stringify(results, null, 2) || 'No results found'
          }]
        };
      }
      
      case 'wiki_get': {
        const { title } = GetArticleSchema.parse(args);
        const article = await getArticle(title);
        if (!article) {
          return {
            content: [{ type: 'text', text: `Article "${title}" not found` }],
            isError: true
          };
        }
        return {
          content: [{
            type: 'text',
            text: `# ${article.title}\n\nTags: ${article.tags || 'none'}\nUpdated: ${article.updated_at}\n\n${article.content}`
          }]
        };
      }
      
      case 'wiki_create': {
        const { title, content, tags } = CreateArticleSchema.parse(args);
        const result = await createArticle(title, content, tags);
        return {
          content: [{ type: 'text', text: `Created article "${result.title}" (id: ${result.id})` }]
        };
      }
      
      case 'wiki_update': {
        const { title, content, tags } = UpdateArticleSchema.parse(args);
        const result = await updateArticle(title, content, tags);
        return {
          content: [{ type: 'text', text: `Updated article "${result.title}"` }]
        };
      }
      
      case 'wiki_list': {
        const { limit, offset } = ListArticlesSchema.parse(args);
        const results = await listArticles(limit, offset);
        return {
          content: [{
            type: 'text',
            text: results.map(r => `- ${r.title} (${r.updated_at})`).join('\n') || 'No articles yet'
          }]
        };
      }
      
      default:
        return {
          content: [{ type: 'text', text: `Unknown tool: ${name}` }],
          isError: true
        };
    }
  } catch (error) {
    return {
      content: [{ type: 'text', text: `Error: ${error.message}` }],
      isError: true
    };
  }
});

// HTTP Server for Web UI
const app = express();
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// HTML template helper
const htmlPage = (title, content) => `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${title} - MCP Wiki</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      line-height: 1.5;
      color: #333;
      max-width: 1200px;
      margin: 0 auto;
      padding: 12px;
      background: #f5f5f5;
    }
    header {
      background: #fff;
      padding: 14px 16px;
      border-radius: 6px;
      margin-bottom: 12px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.1);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    header h1 { 
      color: #2563eb; 
      font-size: 22px;
      margin-bottom: 0;
    }
    header p { display: none; }
    .nav { display: flex; gap: 8px; }
    .nav a {
      padding: 6px 12px;
      background: #2563eb;
      color: white;
      text-decoration: none;
      border-radius: 4px;
      font-size: 13px;
    }
    .nav a:hover { background: #1d4ed8; }
    main {
      background: #fff;
      padding: 16px;
      border-radius: 6px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
    .article-list {
      list-style: none;
    }
    .article-list li {
      padding: 15px;
      border-bottom: 1px solid #eee;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .article-list li:last-child { border-bottom: none; }
    .article-list a {
      color: #2563eb;
      text-decoration: none;
      font-weight: 500;
      font-size: 18px;
    }
    .article-list a:hover { text-decoration: underline; }
    .meta {
      color: #666;
      font-size: 14px;
    }
    .tags {
      display: inline-block;
      background: #e0e7ff;
      color: #3730a3;
      padding: 2px 8px;
      border-radius: 4px;
      font-size: 12px;
      margin-left: 10px;
    }
    /* Enhanced Layout - Compact */
    .search-section {
      display: flex;
      gap: 10px;
      margin-bottom: 15px;
      align-items: center;
    }
    .btn-primary {
      background: #10b981;
      color: white;
      padding: 8px 14px;
      border-radius: 4px;
      text-decoration: none;
      font-weight: 500;
      white-space: nowrap;
      font-size: 14px;
    }
    .btn-primary:hover { background: #059669; }
    /* Stats Bar - Compact */
    .stats-bar {
      display: flex;
      align-items: center;
      gap: 0;
      padding: 12px 16px;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      border-radius: 6px;
      margin-bottom: 15px;
      color: white;
    }
    .stat { 
      text-align: center; 
      flex: 1;
      padding: 0 12px;
      border-right: 1px solid rgba(255,255,255,0.2);
    }
    .stat:last-of-type { border-right: none; }
    .stat-value {
      font-size: 24px;
      font-weight: bold;
      display: block;
      line-height: 1.2;
    }
    .stat-label {
      font-size: 10px;
      opacity: 0.9;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .stat-link {
      color: white;
      text-decoration: none;
      font-size: 12px;
      padding: 6px 12px;
      border: 1px solid rgba(255,255,255,0.3);
      border-radius: 4px;
      display: inline-block;
    }
    .stat-link:hover { background: rgba(255,255,255,0.1); }
    /* Article Grid - Compact */
    .article-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 12px;
    }
    .article-card {
      background: white;
      border-radius: 6px;
      padding: 14px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.1);
      border-left: 3px solid #e5e7eb;
      transition: transform 0.15s, box-shadow 0.15s;
    }
    .article-card:hover {
      transform: translateY(-1px);
      box-shadow: 0 2px 8px rgba(0,0,0,0.12);
    }
    .article-card[data-classification="troubleshooting"] { border-left-color: #ef4444; }
    .article-card[data-classification="tutorial"] { border-left-color: #10b981; }
    .article-card[data-classification="reference"] { border-left-color: #3b82f6; }
    .article-card[data-classification="architecture"] { border-left-color: #8b5cf6; }
    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 6px;
    }
    .card-title {
      color: #1f2937;
      text-decoration: none;
      font-size: 15px;
      font-weight: 600;
      line-height: 1.3;
    }
    .card-title:hover { color: #2563eb; }
    .quality-badge {
      color: #f59e0b;
      font-size: 14px;
      line-height: 1;
    }
    .card-summary {
      color: #6b7280;
      font-size: 12px;
      line-height: 1.4;
      margin-bottom: 10px;
      max-height: 34px;
      overflow: hidden;
    }
    .card-meta {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 6px;
    }
    .classification-tag {
      font-size: 9px;
      padding: 2px 6px;
      border-radius: 3px;
      text-transform: uppercase;
      font-weight: 600;
      letter-spacing: 0.3px;
    }
    .classification-tag.troubleshooting { background: #fee2e2; color: #991b1b; }
    .classification-tag.tutorial { background: #d1fae5; color: #065f46; }
    .classification-tag.reference { background: #dbeafe; color: #1e40af; }
    .classification-tag.architecture { background: #ede9fe; color: #5b21b6; }
    .classification-tag.uncategorized { background: #f3f4f6; color: #6b7280; }
    .classification-tag.documentation { background: #fef3c7; color: #92400e; }
    .date { color: #9ca3af; font-size: 11px; }
    .card-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
    .tag {
      background: #f3f4f6;
      color: #4b5563;
      padding: 1px 6px;
      border-radius: 3px;
      font-size: 10px;
    }
    .enhance-prompt {
      margin-top: 8px;
      padding-top: 8px;
      border-top: 1px dashed #e5e7eb;
    }
    .btn-small {
      background: #8b5cf6;
      color: white;
      padding: 4px 10px;
      border-radius: 3px;
      text-decoration: none;
      font-size: 11px;
      display: inline-block;
    }
    .btn-small:hover { background: #7c3aed; }
    .empty-state {
      text-align: center;
      padding: 40px 20px;
      background: white;
      border-radius: 6px;
    }
    .empty-state p {
      color: #6b7280;
      font-size: 16px;
      margin-bottom: 15px;
    }
    form { max-width: 600px; }
    .form-group {
      margin-bottom: 20px;
    }
    label {
      display: block;
      margin-bottom: 5px;
      font-weight: 500;
    }
    input[type="text"], textarea {
      width: 100%;
      padding: 10px;
      border: 1px solid #ddd;
      border-radius: 4px;
      font-size: 16px;
      font-family: inherit;
    }
    textarea { min-height: 300px; resize: vertical; }
    button {
      background: #2563eb;
      color: white;
      border: none;
      padding: 12px 24px;
      border-radius: 4px;
      cursor: pointer;
      font-size: 16px;
    }
    button:hover { background: #1d4ed8; }
    .search-box {
      display: flex;
      gap: 8px;
      margin-bottom: 0;
      flex: 1;
    }
    .search-box input { 
      flex: 1; 
      padding: 8px 12px;
      font-size: 14px;
    }
    .search-box button {
      padding: 8px 16px;
      font-size: 14px;
    }
    .article-content {
      white-space: pre-wrap;
      line-height: 1.8;
      font-size: 16px;
    }
    .article-content h1, .article-content h2, .article-content h3 {
      margin: 20px 0 10px;
    }
    .article-content p { margin-bottom: 15px; }
    .actions {
      display: flex;
      gap: 10px;
      margin-top: 20px;
    }
    .actions a {
      padding: 8px 16px;
      background: #6b7280;
      color: white;
      text-decoration: none;
      border-radius: 4px;
      font-size: 14px;
    }
    .actions a.edit { background: #2563eb; }
    .actions a:hover { opacity: 0.9; }
    .error {
      background: #fef2f2;
      color: #dc2626;
      padding: 15px;
      border-radius: 4px;
      margin-bottom: 20px;
    }
    .success {
      background: #f0fdf4;
      color: #16a34a;
      padding: 15px;
      border-radius: 4px;
      margin-bottom: 20px;
    }
    /* Mermaid diagram styling */
    .mermaid {
      background: #fafafa;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      padding: 20px;
      margin: 20px 0;
      text-align: center;
    }
    pre:has(code.language-mermaid) {
      background: transparent;
      padding: 0;
      margin: 20px 0;
    }
    pre code.language-mermaid {
      display: none; /* Hide raw mermaid code, let mermaid render SVG */
    }
    /* AI Metadata Section */
    .ai-metadata {
      background: linear-gradient(135deg, #f3e8ff 0%, #e0e7ff 100%);
      border-radius: 8px;
      padding: 15px 20px;
      margin-bottom: 20px;
      border-left: 4px solid #8b5cf6;
    }
    .ai-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 10px;
    }
    .ai-badge {
      background: #8b5cf6;
      color: white;
      padding: 4px 10px;
      border-radius: 4px;
      font-size: 13px;
      font-weight: 500;
    }
    .quality-score {
      color: #6b7280;
      font-size: 13px;
    }
    .ai-tldr {
      background: white;
      padding: 12px 15px;
      border-radius: 6px;
      margin-bottom: 10px;
      font-size: 14px;
      line-height: 1.6;
      color: #374151;
    }
    .ai-tags {
      display: flex;
      gap: 8px;
    }
    .ai-prompt {
      background: #fef3c7;
      border: 2px dashed #f59e0b;
      border-radius: 8px;
      padding: 20px;
      text-align: center;
      margin-bottom: 20px;
    }
    .ai-prompt p {
      color: #92400e;
      margin-bottom: 12px;
    }
  </style>
</head>
<body>
  <header>
    <h1>MCP Wiki</h1>
    <p>Team knowledge base (SQLite-backed)</p>
    <div class="nav">
      <a href="/">Home</a>
      <a href="/new">New Article</a>
    </div>
  </header>
  <main>${content}</main>
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <script>
    mermaid.initialize({
      startOnLoad: true,
      theme: 'default',
      securityLevel: 'loose'
    });
  </script>
</body>
</html>`;

// Routes
app.get('/health', (req, res) => {
  res.json({ status: 'ok', db: DB_PATH, articles: null });
});

// Home / List
app.get('/', async (req, res) => {
  try {
    const articles = await listArticles(50, 0);
    
    const enhancedCount = articles.filter(a => a.metadata && a.metadata.classification).length;
    const avgQuality = articles.length > 0 
      ? (articles.reduce((sum, a) => sum + (a.metadata?.quality_score || 0), 0) / articles.length).toFixed(2)
      : 0;
    
    const searchForm = `
      <div class="search-section">
        <form action="/search" method="GET" class="search-box">
          <input type="text" name="q" placeholder="Search articles..." required>
          <button type="submit">Search</button>
        </form>
        <a href="/new" class="btn-primary">+ New Article</a>
      </div>
    `;
    
    const statsBar = articles.length > 0 ? `
      <div class="stats-bar">
        <div class="stat">
          <span class="stat-value">${articles.length}</span>
          <span class="stat-label">Articles</span>
        </div>
        <div class="stat">
          <span class="stat-value">${enhancedCount}</span>
          <span class="stat-label">AI Enhanced</span>
        </div>
        <div class="stat">
          <span class="stat-value">${avgQuality}</span>
          <span class="stat-label">Avg Quality</span>
        </div>
        <div class="stat">
          <a href="/admin" class="stat-link">View Health →</a>
        </div>
      </div>
    ` : '';
    
    const list = articles.length === 0 
      ? '<div class="empty-state"><p>No articles yet.</p><a href="/new" class="btn-primary">Create First Article</a></div>'
      : '<div class="article-grid">' + articles.map(a => {
          const metadata = a.metadata || {};
          const qualityScore = metadata.quality_score || 0;
          const classification = metadata.classification || 'uncategorized';
          const hasTLDR = metadata.tldr && metadata.tldr.length > 10;
          
          return `
            <article class="article-card" data-classification="${classification}">
              <div class="card-header">
                <a href="/article/${encodeURIComponent(a.title)}" class="card-title">${escapeHtml(a.title)}</a>
                <span class="quality-badge" title="Quality: ${qualityScore.toFixed(2)}">${qualityScore >= 0.8 ? '★' : qualityScore >= 0.6 ? '◆' : '◇'}</span>
              </div>
              ${hasTLDR ? `<p class="card-summary">${escapeHtml(metadata.tldr.substring(0, 100))}...</p>` : ''}
              <div class="card-meta">
                <span class="classification-tag ${classification}">${classification}</span>
                <span class="date">${formatDate(a.updated_at)}</span>
              </div>
              ${a.tags ? `<div class="card-tags">${(Array.isArray(a.tags) ? a.tags : a.tags.split(',')).slice(0, 3).map(t => `<span class="tag">${escapeHtml(t.trim())}</span>`).join('')}</div>` : ''}
              ${!metadata.classification ? `<div class="enhance-prompt"><a href="/enhance/${a.id}" class="btn-small">✨ Enhance</a></div>` : ''}
            </article>
          `;
        }).join('') + '</div>';
    
    res.send(htmlPage('Home', searchForm + statsBar + list));
  } catch (err) {
    res.send(htmlPage('Error', `<div class="error">${escapeHtml(err.message)}</div>`));
  }
});

// Search
app.get('/search', async (req, res) => {
  const query = req.query.q || '';
  try {
    const articles = query ? await searchArticles(query, 20) : [];
    const searchForm = `
      <form action="/search" method="GET" class="search-box">
        <input type="text" name="q" value="${escapeHtml(query)}" placeholder="Search articles..." required>
        <button type="submit">Search</button>
      </form>
    `;
    const results = articles.length === 0
      ? '<p>No results found.</p>'
      : '<ul class="article-list">' + articles.map(a => `
        <li>
          <div>
            <a href="/article/${encodeURIComponent(a.title)}">${escapeHtml(a.title)}</a>
            ${a.tags ? (Array.isArray(a.tags) ? a.tags : a.tags.split(',')).map(t => `<span class="tags">${escapeHtml(t.trim())}</span>`).join('') : ''}
          </div>
          <span class="meta">${a.updated_at}</span>
        </li>
      `).join('') + '</ul>';
    
    res.send(htmlPage(`Search: ${query}`, searchForm + results));
  } catch (err) {
    res.send(htmlPage('Error', `<div class="error">${escapeHtml(err.message)}</div>`));
  }
});

// View Article
app.get('/article/:title', async (req, res) => {
  try {
    const article = await getArticle(req.params.title);
    if (!article) {
      return res.status(404).send(htmlPage('Not Found', `
        <p>Article not found.</p>
        <p><a href="/new?title=${encodeURIComponent(req.params.title)}">Create it</a></p>
      `));
    }
    
    const metadata = article.metadata || {};
    const tagsDisplay = article.tags 
      ? (Array.isArray(article.tags) ? article.tags.join(', ') : article.tags)
      : 'none';
    const hasEnhancement = metadata.classification || metadata.tldr;
    
    const aiSection = hasEnhancement ? `
      <div class="ai-metadata">
        <div class="ai-header">
          <span class="ai-badge">✨ AI Enhanced</span>
          ${metadata.quality_score ? `<span class="quality-score">Quality: ${metadata.quality_score.toFixed(2)}/1.0</span>` : ''}
        </div>
        ${metadata.tldr ? `<div class="ai-tldr"><strong>TL;DR:</strong> ${escapeHtml(metadata.tldr)}</div>` : ''}
        <div class="ai-tags">
          ${metadata.classification ? `<span class="classification-tag ${metadata.classification}">${metadata.classification}</span>` : ''}
        </div>
      </div>
    ` : `
      <div class="ai-prompt">
        <p>This article hasn't been enhanced with AI yet.</p>
        <a href="/enhance/${article.id}" class="btn-small">✨ Enhance with AI</a>
      </div>
    `;
    
    const content = `
      <h1>${escapeHtml(article.title)}</h1>
      ${aiSection}
      <p class="meta">Updated ${formatDate(article.updated_at)} · ${Math.round(article.content.length / 5)} words · Tags: ${escapeHtml(tagsDisplay)}</p>
      <div class="article-content">${renderArticleContent(article.content)}</div>
      <div class="actions">
        <a href="/edit/${encodeURIComponent(article.title)}" class="edit">Edit</a>
        <a href="/">Back to Home</a>
        <button onclick="processQueue()" class="btn-process">🔄 Process Queue</button>
        <span id="queue-status" class="queue-status"></span>
      </div>
      <script>
        async function processQueue() {
          const btn = document.querySelector('.btn-process');
          const status = document.getElementById('queue-status');
          btn.disabled = true;
          status.textContent = 'Processing...';
          
          try {
            const response = await fetch('/api/admin/process-queue', { method: 'POST' });
            const data = await response.json();
            
            if (response.ok) {
              status.textContent = data.pending_jobs + ' jobs queued for processing';
              // Poll for updates
              setTimeout(checkQueueStatus, 2000);
            } else {
              status.textContent = 'Error: ' + (data.error || 'Failed');
              btn.disabled = false;
            }
          } catch (err) {
            status.textContent = 'Error: ' + err.message;
            btn.disabled = false;
          }
        }
        
        async function checkQueueStatus() {
          try {
            const response = await fetch('/api/admin/queue-status');
            const data = await response.json();
            const status = document.getElementById('queue-status');
            const btn = document.querySelector('.btn-process');
            
            status.textContent = 'Queue: ' + data.stats.pending + ' pending, ' + data.stats.completed + ' done';
            
            if (data.stats.pending === 0) {
              status.textContent += ' ✅ Complete!';
            }
            
            btn.disabled = false;
          } catch (err) {
            console.error('Failed to check queue status:', err);
          }
        }
        
        // Check status on page load
        checkQueueStatus();
      </script>
      <style>
        .btn-process {
          background: #8b5cf6;
          color: white;
          padding: 8px 16px;
          border: none;
          border-radius: 4px;
          cursor: pointer;
          font-size: 14px;
        }
        .btn-process:hover:not(:disabled) { background: #7c3aed; }
        .btn-process:disabled { opacity: 0.6; cursor: not-allowed; }
        .queue-status {
          margin-left: 10px;
          font-size: 12px;
          color: #6b7280;
        }
      </style>
    `;
    res.send(htmlPage(article.title, content));
  } catch (err) {
    res.send(htmlPage('Error', `<div class="error">${escapeHtml(err.message)}</div>`));
  }
});

// Web UI: Enhance Article
app.get('/enhance/:id', async (req, res) => {
  try {
    const articleId = parseInt(req.params.id);
    
    const result = await pgPool.query(
      'SELECT title FROM articles WHERE id = $1',
      [articleId]
    );
    
    if (result.rows.length === 0) {
      return res.status(404).send(htmlPage('Not Found', '<p>Article not found.</p>'));
    }
    
    const title = result.rows[0].title;
    
    await pgPool.query(
      `INSERT INTO article_ai_queue (article_id, action, status) 
       VALUES ($1, 'classify', 'pending'), ($1, 'summarize', 'pending')`,
      [articleId]
    );
    
    const content = `
      <div class="success">
        <h2>✨ Enhancement Queued</h2>
        <p>AI enhancement jobs have been queued for "${escapeHtml(title)}".</p>
        <p>Classification and summary generation are in progress.</p>
      </div>
      <div class="actions">
        <a href="/article/${encodeURIComponent(title)}">View Article</a>
        <a href="/">Back to Home</a>
      </div>
    `;
    res.send(htmlPage('Enhancement Queued', content));
  } catch (err) {
    res.send(htmlPage('Error', `<div class="error">${escapeHtml(err.message)}</div>`));
  }
});

// Web UI: Admin Dashboard
app.get('/admin', async (req, res) => {
  try {
    const articlesResult = await pgPool.query(`
      SELECT id, title, updated_at, metadata,
             LENGTH(content) as char_count,
             metadata->>'classification' as classification,
             metadata->>'quality_score' as quality_score
      FROM articles ORDER BY updated_at DESC
    `);
    
    const jobsResult = await pgPool.query(`
      SELECT COUNT(*) FILTER (WHERE status = 'pending') as pending,
             COUNT(*) FILTER (WHERE status = 'completed') as completed,
             COUNT(*) FILTER (WHERE status = 'failed') as failed
      FROM article_ai_queue
    `);
    
    const articles = articlesResult.rows;
    const jobs = jobsResult.rows[0];
    const enhancedCount = articles.filter(a => a.classification).length;
    
    const stats = `
      <div class="stats-bar">
        <div class="stat"><span class="stat-value">${articles.length}</span><span class="stat-label">Total</span></div>
        <div class="stat"><span class="stat-value">${enhancedCount}</span><span class="stat-label">Enhanced</span></div>
        <div class="stat"><span class="stat-value">${jobs.pending}</span><span class="stat-label">Pending Jobs</span></div>
        <div class="stat"><span class="stat-value">${jobs.completed}</span><span class="stat-label">Completed Jobs</span></div>
      </div>
    `;
    
    const articleList = articles.map(a => {
      const score = a.quality_score ? parseFloat(a.quality_score) : 0;
      const needsAttention = !a.classification || score < 0.5;
      return `
        <tr class="${needsAttention ? 'needs-attention' : ''}">
          <td><a href="/article/${encodeURIComponent(a.title)}">${escapeHtml(a.title.substring(0, 50))}</a></td>
          <td>${a.classification || '<span class="badge-pending">pending</span>'}</td>
          <td>${score ? score.toFixed(2) : '-'}</td>
          <td>${formatDate(a.updated_at)}</td>
          <td>${!a.classification ? `<a href="/enhance/${a.id}" class="btn-small">Enhance</a>` : '✓'}</td>
        </tr>
      `;
    }).join('');
    
    const content = `
      <h1>Wiki Health Dashboard</h1>
      ${stats}
      <table class="admin-table">
        <thead>
          <tr><th>Title</th><th>Classification</th><th>Quality</th><th>Updated</th><th>Action</th></tr>
        </thead>
        <tbody>${articleList}</tbody>
      </table>
      <style>
        .admin-table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        .admin-table th, .admin-table td { padding: 12px; text-align: left; border-bottom: 1px solid #e5e7eb; }
        .admin-table th { background: #f9fafb; font-weight: 600; }
        .admin-table tr:hover { background: #f9fafb; }
        .admin-table tr.needs-attention { background: #fef2f2; }
        .badge-pending { background: #fef3c7; color: #92400e; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
      </style>
    `;
    res.send(htmlPage('Admin Dashboard', content));
  } catch (err) {
    res.send(htmlPage('Error', `<div class="error">${escapeHtml(err.message)}</div>`));
  }
});

// New Article Form
app.get('/new', (req, res) => {
  const title = req.query.title || '';
  const form = `
    <h1>New Article</h1>
    <form action="/create" method="POST">
      <div class="form-group">
        <label>Title</label>
        <input type="text" name="title" value="${escapeHtml(title)}" required>
      </div>
      <div class="form-group">
        <label>Content (Markdown supported)</label>
        <textarea name="content" required></textarea>
      </div>
      <div class="form-group">
        <label>Tags (comma-separated)</label>
        <input type="text" name="tags" placeholder="e.g., devops, deployment">
      </div>
      <button type="submit">Create Article</button>
    </form>
  `;
  res.send(htmlPage('New Article', form));
});

// Create Article
app.post('/create', async (req, res) => {
  const { title, content, tags } = req.body;
  try {
    const tagList = tags ? tags.split(',').map(t => t.trim()).filter(Boolean) : [];
    await createArticle(title, content, tagList);
    res.redirect(`/article/${encodeURIComponent(title)}`);
  } catch (err) {
    res.send(htmlPage('Error', `
      <div class="error">${escapeHtml(err.message)}</div>
      <p><a href="/new">Try again</a></p>
    `));
  }
});

// Edit Form
app.get('/edit/:title', async (req, res) => {
  try {
    const article = await getArticle(req.params.title);
    if (!article) {
      return res.status(404).send(htmlPage('Not Found', '<p>Article not found.</p>'));
    }
    
    const form = `
      <h1>Edit: ${escapeHtml(article.title)}</h1>
      <form action="/update" method="POST">
        <input type="hidden" name="title" value="${escapeHtml(article.title)}">
        <div class="form-group">
          <label>Content</label>
          <textarea name="content" required>${escapeHtml(article.content)}</textarea>
        </div>
        <div class="form-group">
          <label>Tags (comma-separated)</label>
          <input type="text" name="tags" value="${escapeHtml(Array.isArray(article.tags) ? article.tags.join(', ') : (article.tags || ''))}">
        </div>
        <button type="submit">Update Article</button>
      </form>
    `;
    res.send(htmlPage(`Edit: ${article.title}`, form));
  } catch (err) {
    res.send(htmlPage('Error', `<div class="error">${escapeHtml(err.message)}</div>`));
  }
});

// Update Article
app.post('/update', async (req, res) => {
  const { title, content, tags } = req.body;
  try {
    const tagList = tags ? tags.split(',').map(t => t.trim()).filter(Boolean) : [];
    await updateArticle(title, content, tagList);
    res.redirect(`/article/${encodeURIComponent(title)}`);
  } catch (err) {
    res.send(htmlPage('Error', `
      <div class="error">${escapeHtml(err.message)}</div>
      <p><a href="/edit/${encodeURIComponent(title)}">Try again</a></p>
    `));
  }
});

// API Endpoints (JSON)
app.get('/api/articles', async (req, res) => {
  try {
    const articles = await listArticles(
      parseInt(req.query.limit) || 20,
      parseInt(req.query.offset) || 0
    );
    res.json(articles);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.get('/api/articles/:title', async (req, res) => {
  try {
    const article = await getArticle(req.params.title);
    if (!article) return res.status(404).json({ error: 'Not found' });
    res.json(article);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.post('/api/articles', async (req, res) => {
  try {
    const { title, content, tags, entities, classification } = req.body;
    if (!title || !content) {
      return res.status(400).json({ error: 'Title and content required' });
    }
    const tagList = tags ? (Array.isArray(tags) ? tags : tags.split(',').map(t => t.trim()).filter(Boolean)) : [];
    const result = await createArticle(title, content, tagList, entities, classification);
    res.status(201).json(result);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.put('/api/articles/:title', async (req, res) => {
  try {
    const { content, tags, entities, classification } = req.body;
    if (!content) {
      return res.status(400).json({ error: 'Content required' });
    }
    const tagList = tags ? (Array.isArray(tags) ? tags : tags.split(',').map(t => t.trim()).filter(Boolean)) : [];
    const result = await updateArticle(req.params.title, content, tagList, entities, classification);
    res.json(result);
  } catch (err) {
    if (err.message.includes('not found')) {
      return res.status(404).json({ error: 'Article not found' });
    }
    res.status(500).json({ error: err.message });
  }
});

app.get('/api/search', async (req, res) => {
  try {
    const query = req.query.q || '';
    const limit = parseInt(req.query.limit) || 20;
    if (!query) return res.json([]);
    const articles = await searchArticles(query, limit);
    res.json(articles);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// AI Enhancement Endpoints
app.post('/api/articles/:id/enhance', async (req, res) => {
  try {
    const articleId = parseInt(req.params.id);
    const { actions = ['classify'] } = req.body;
    
    // Validate actions
    const validActions = ['classify', 'summarize', 'suggest-links', 'embed'];
    const requestedActions = actions.filter(a => validActions.includes(a));
    
    if (requestedActions.length === 0) {
      return res.status(400).json({ error: 'No valid actions specified' });
    }
    
    // Queue jobs
    const jobs = [];
    for (const action of requestedActions) {
      const result = await pgPool.query(
        `INSERT INTO article_ai_queue (article_id, action, status) 
         VALUES ($1, $2, 'pending') 
         RETURNING id, action, status, created_at`,
        [articleId, action]
      );
      jobs.push(result.rows[0]);
    }
    
    res.json({ 
      message: 'Enhancement jobs queued',
      article_id: articleId,
      jobs: jobs
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.get('/api/articles/:id/enhance-status/:jobId', async (req, res) => {
  try {
    const result = await pgPool.query(
      `SELECT id, article_id, action, status, result, error, created_at, processed_at 
       FROM article_ai_queue WHERE id = $1 AND article_id = $2`,
      [req.params.jobId, req.params.id]
    );
    
    if (result.rows.length === 0) {
      return res.status(404).json({ error: 'Job not found' });
    }
    
    res.json(result.rows[0]);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.get('/api/articles/:id/suggestions', async (req, res) => {
  try {
    const articleId = parseInt(req.params.id);
    
    // Get article metadata
    const articleResult = await pgPool.query(
      'SELECT metadata FROM articles WHERE id = $1',
      [articleId]
    );
    
    if (articleResult.rows.length === 0) {
      return res.status(404).json({ error: 'Article not found' });
    }
    
    const metadata = articleResult.rows[0].metadata || {};
    
    res.json({
      article_id: articleId,
      suggested_tags: metadata.suggested_tags || [],
      classification: metadata.classification || null,
      tldr: metadata.tldr || null,
      related_articles: metadata.related_articles || [],
      missing_links: metadata.missing_links || [],
      quality_score: metadata.quality_score || null
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.get('/api/articles/:id/tldr', async (req, res) => {
  try {
    const articleId = parseInt(req.params.id);
    
    const result = await pgPool.query(
      'SELECT metadata->>\'tldr\' as tldr FROM articles WHERE id = $1',
      [articleId]
    );
    
    if (result.rows.length === 0) {
      return res.status(404).json({ error: 'Article not found' });
    }
    
    res.json({
      article_id: articleId,
      tldr: result.rows[0].tldr || 'No summary available. Queue an enhancement job.'
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.get('/api/admin/article-health', async (req, res) => {
  try {
    const limit = parseInt(req.query.limit) || 50;
    
    const result = await pgPool.query(`
      SELECT 
        a.id,
        a.title,
        a.updated_at,
        EXTRACT(DAY FROM (NOW() - a.updated_at)) as staleness_days,
        LENGTH(a.content) as word_count,
        a.metadata->>'quality_score' as quality_score,
        a.metadata->>'classification' as classification,
        CASE 
          WHEN a.metadata IS NULL OR a.metadata = '{}' THEN false
          ELSE true
        END as has_metadata
      FROM articles a
      ORDER BY a.updated_at DESC
      LIMIT $1
    `, [limit]);
    
    res.json({
      total: result.rows.length,
      articles: result.rows.map(row => ({
        ...row,
        needs_attention: !row.has_metadata || row.staleness_days > 90 || row.word_count < 200
      }))
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Process AI Enhancement Queue (triggers processing of pending jobs)
app.post('/api/admin/process-queue', async (req, res) => {
  try {
    // Count pending jobs before processing
    const pendingResult = await pgPool.query(
      "SELECT COUNT(*) as count FROM article_ai_queue WHERE status = 'pending'"
    );
    const pendingCount = parseInt(pendingResult.rows[0].count);
    
    // Trigger ai-worker to process jobs (exec the worker script)
    // We return immediately with job count, actual processing happens async
    // Client should poll /api/admin/queue-status to see progress
    
    res.json({
      message: 'Queue processing triggered',
      pending_jobs: pendingCount,
      note: 'Processing runs asynchronously. Check /api/admin/queue-status for progress.'
    });
    
    // Fire-and-forget: trigger actual processing
    // Note: In production, this should use a proper job scheduler
    // For now, we just return status immediately
    
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Get Queue Status
app.get('/api/admin/queue-status', async (req, res) => {
  try {
    const result = await pgPool.query(`
      SELECT 
        COUNT(*) FILTER (WHERE status = 'pending') as pending,
        COUNT(*) FILTER (WHERE status = 'done') as completed,
        COUNT(*) FILTER (WHERE status = 'error') as errors,
        MAX(created_at) as last_job_created,
        MAX(processed_at) as last_job_processed
      FROM article_ai_queue
    `);
    
    const stats = result.rows[0];
    
    // Get recent pending jobs (top 5)
    const pendingResult = await pgPool.query(`
      SELECT aq.id, aq.action, aq.created_at, a.title as article_title
      FROM article_ai_queue aq
      JOIN articles a ON a.id = aq.article_id
      WHERE aq.status = 'pending'
      ORDER BY aq.created_at ASC
      LIMIT 5
    `);
    
    res.json({
      stats: {
        pending: parseInt(stats.pending),
        completed: parseInt(stats.completed),
        errors: parseInt(stats.errors),
        last_job_created: stats.last_job_created,
        last_job_processed: stats.last_job_processed
      },
      recent_pending: pendingResult.rows
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Helper
function escapeHtml(text) {
  if (!text) return '';
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Process article content - convert markdown-like syntax and mermaid diagrams
function renderArticleContent(text) {
  if (!text) return '';
  
  // Escape HTML first for safety
  let html = escapeHtml(text);
  
  // Convert ```mermaid blocks to mermaid divs
  // Pattern: ```mermaid\n[content]\n```
  html = html.replace(/```mermaid\n([\s\S]*?)```/g, (match, content) => {
    const diagramId = 'mermaid-' + Math.random().toString(36).substr(2, 9);
    return `<div class="mermaid" id="${diagramId}">${content.trim()}</div>`;
  });
  
  // Convert regular code blocks
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (match, lang, content) => {
    if (lang === 'mermaid') return match; // Already handled above
    return `<pre><code class="language-${lang}">${content.trim()}</code></pre>`;
  });
  
  // Convert inline code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  
  // Convert headers
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  
  // Convert bold and italic
  html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
  
  // Convert bullet lists
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');
  
  // Convert numbered lists
  html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
  
  // Convert links [text](url)
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>');
  
  // Convert paragraphs (lines separated by blank lines)
  html = html.replace(/\n\n/g, '</p><p>');
  
  // Wrap in paragraph if not already wrapped
  if (!html.startsWith('<')) {
    html = '<p>' + html + '</p>';
  }
  
  // Fix table formatting - preserve pre-formatted tables
  html = html.replace(/\|(.+)\|/g, (match) => {
    // Simple table row handling
    if (match.includes('---')) {
      return match; // Separator row
    }
    return '<tr>' + match.split('|').filter(c => c.trim()).map(c => `<td>${c.trim()}</td>`).join('') + '</tr>';
  });
  
  return html;
}

// Initialize database and start servers
async function start() {
  // Initialize database (SQLite or PostgreSQL)
  await initDatabase();
  
  // Start HTTP server
  app.listen(HTTP_PORT, () => {
    console.error(`mcp-wiki: HTTP server started on port ${HTTP_PORT}`);
  });
  
  // MCP stdio transport (optional - only if stdin is piped)
  // This runs after HTTP server starts, allowing dual-mode operation
  const isStdioMode = !process.stdin.isTTY || process.env.MCP_STDIO === '1';
  if (isStdioMode) {
    const transport = new StdioServerTransport();
    server.connect(transport).then(() => {
      console.error('mcp-wiki: MCP stdio transport connected');
    }).catch(err => {
      console.error('mcp-wiki: MCP stdio connection failed:', err.message);
    });
  } else {
    console.error('mcp-wiki: Running in HTTP-only mode (no MCP stdio client detected)');
    console.error(`mcp-wiki: Visit http://localhost:${HTTP_PORT}/ to use the wiki`);
  }
}

start().catch(err => {
  console.error('mcp-wiki: Failed to start:', err.message);
  process.exit(1);
});
