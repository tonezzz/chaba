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
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

async function listArticles(limit, offset) {
  if (USE_POSTGRES) {
    const result = await pgPool.query(
      `SELECT title, tags, created_at, updated_at 
       FROM articles ORDER BY updated_at DESC LIMIT $1 OFFSET $2`,
      [limit, offset]
    );
    return result.rows;
  } else {
    // SQLite
    return new Promise((resolve, reject) => {
      db.all(
        `SELECT title, tags, created_at, updated_at FROM articles ORDER BY updated_at DESC LIMIT ? OFFSET ?`,
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
      line-height: 1.6;
      color: #333;
      max-width: 1200px;
      margin: 0 auto;
      padding: 20px;
      background: #f5f5f5;
    }
    header {
      background: #fff;
      padding: 20px;
      border-radius: 8px;
      margin-bottom: 20px;
      box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    header h1 { color: #2563eb; margin-bottom: 10px; }
    .nav { display: flex; gap: 10px; margin-top: 10px; }
    .nav a {
      padding: 8px 16px;
      background: #2563eb;
      color: white;
      text-decoration: none;
      border-radius: 4px;
      font-size: 14px;
    }
    .nav a:hover { background: #1d4ed8; }
    main {
      background: #fff;
      padding: 30px;
      border-radius: 8px;
      box-shadow: 0 2px 4px rgba(0,0,0,0.1);
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
      gap: 10px;
      margin-bottom: 20px;
    }
    .search-box input { flex: 1; }
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
    const searchForm = `
      <form action="/search" method="GET" class="search-box">
        <input type="text" name="q" placeholder="Search articles..." required>
        <button type="submit">Search</button>
      </form>
    `;
    const list = articles.length === 0 
      ? '<p>No articles yet. <a href="/new">Create one</a></p>'
      : '<ul class="article-list">' + articles.map(a => `
        <li>
          <div>
            <a href="/article/${encodeURIComponent(a.title)}">${escapeHtml(a.title)}</a>
            ${a.tags ? a.tags.split(',').map(t => `<span class="tags">${escapeHtml(t.trim())}</span>`).join('') : ''}
          </div>
          <span class="meta">${a.updated_at}</span>
        </li>
      `).join('') + '</ul>';
    
    res.send(htmlPage('Home', searchForm + list));
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
            ${a.tags ? a.tags.split(',').map(t => `<span class="tags">${escapeHtml(t.trim())}</span>`).join('') : ''}
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
    
    const content = `
      <h1>${escapeHtml(article.title)}</h1>
      <p class="meta">Updated: ${article.updated_at} | Tags: ${article.tags || 'none'}</p>
      <div class="article-content">${renderArticleContent(article.content)}</div>
      <div class="actions">
        <a href="/edit/${encodeURIComponent(article.title)}" class="edit">Edit</a>
        <a href="/">Back</a>
      </div>
    `;
    res.send(htmlPage(article.title, content));
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
          <input type="text" name="tags" value="${escapeHtml(article.tags || '')}">
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
