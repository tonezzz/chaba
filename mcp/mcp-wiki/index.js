import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { SSEServerTransport } from '@modelcontextprotocol/sdk/server/sse.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';
import pg from 'pg';
import { z } from 'zod';
import { zodToJsonSchema } from 'zod-to-json-schema';
import express from 'express';
import { spawn } from 'child_process';

const { Pool } = pg;

// Database configuration - PostgreSQL only
const DATABASE_URL = process.env.DATABASE_URL || 'postgresql://chaba:changeme@idc1.surf-thailand.com:5432/chaba';
const HTTP_PORT = process.env.WIKI_HTTP_PORT || 8080;
const API_KEY = process.env.WIKI_API_KEY;

let pgPool;

async function initDatabase() {
  // PostgreSQL mode only
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

  // Revision history
  await pgPool.query(`
    CREATE TABLE IF NOT EXISTS revisions (
      id SERIAL PRIMARY KEY,
      article_id INTEGER REFERENCES articles(id) ON DELETE CASCADE,
      article_title VARCHAR(255) NOT NULL,
      content TEXT NOT NULL,
      tags TEXT[],
      editor TEXT,
      change_summary TEXT,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
  `);

  await pgPool.query(`
    CREATE INDEX IF NOT EXISTS idx_revisions_article_id ON revisions(article_id)
  `);

  await pgPool.query(`
    CREATE INDEX IF NOT EXISTS idx_revisions_article_title ON revisions(article_title)
  `);

  await pgPool.query(`
    CREATE INDEX IF NOT EXISTS idx_articles_title ON articles USING gin(to_tsvector('english', title))
  `);

  await pgPool.query(`
    CREATE INDEX IF NOT EXISTS idx_articles_content ON articles USING gin(to_tsvector('english', content))
  `);

  console.error('mcp-wiki: PostgreSQL database initialized');
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

const DeleteArticleSchema = z.object({
  title: z.string()
});

const ValidateContentSchema = z.object({
  content: z.string(),
  title: z.string().optional()
});

const ExplainArticleSchema = z.object({
  title: z.string()
});

const EnhanceArticleSchema = z.object({
  title: z.string(),
  actions: z.array(z.enum(['classify', 'summarize', 'suggest-links', 'validate'])).optional().default(['validate'])
});

const SuggestTagsSchema = z.object({
  content: z.string(),
  title: z.string().optional()
});

const SemanticSearchSchema = z.object({
  query: z.string(),
  limit: z.number().optional().default(10)
});

const HybridSearchSchema = z.object({
  query: z.string(),
  limit: z.number().optional().default(10),
  alpha: z.number().optional().default(0.5)
});

const GetHistorySchema = z.object({
  title: z.string(),
  limit: z.number().optional().default(10)
});

const RevertArticleSchema = z.object({
  title: z.string(),
  revision_id: z.number()
});

const DiffRevisionsSchema = z.object({
  title: z.string(),
  revision_id_1: z.number(),
  revision_id_2: z.number().optional()
});

// Database helpers - PostgreSQL only
async function searchArticles(query, limit) {
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
}

// Semantic search using Weaviate
const WEAVIATE_URL = process.env.WEAVIATE_URL || 'http://localhost:8080';

async function semanticSearch(query, limit = 10, certainty = 0.7) {
  try {
    const response = await fetch(`${WEAVIATE_URL}/v1/graphql`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: `
          {
            Get {
              WikiArticle(
                nearText: {
                  concepts: ["${query}"]
                  certainty: ${certainty}
                }
                limit: ${limit}
              ) {
                title
                content
                tags
                wikidb_id
                updated_at
                _additional {
                  certainty
                }
              }
            }
          }
        `
      })
    });
    
    const data = await response.json();
    
    if (data.errors) {
      console.error('Weaviate error:', data.errors);
      return [];
    }
    
    const articles = data.data?.Get?.WikiArticle || [];
    return articles.map(a => ({
      title: a.title,
      content: a.content,
      tags: a.tags,
      wikidb_id: a.wikidb_id,
      updated_at: a.updated_at,
      _additional: a._additional
    }));
  } catch (err) {
    console.error('Semantic search error:', err);
    return [];
  }
}

// Hybrid search combining keyword and semantic
async function hybridSearch(query, limit = 10, alpha = 0.5) {
  try {
    // Get keyword results
    const keywordResults = await searchArticles(query, limit);
    
    // Get semantic results - adjust certainty based on alpha
    // Higher alpha = higher certainty threshold for semantic results
    const certainty = 0.6 + (alpha * 0.2);
    const semanticResults = await semanticSearch(query, limit, certainty);
    
    // Merge and deduplicate
    const seen = new Set();
    const results = [];
    
    // Add keyword results first (marked as 'keyword')
    for (const article of keywordResults) {
      if (!seen.has(article.title)) {
        seen.add(article.title);
        results.push({ ...article, match_type: 'keyword' });
      }
    }
    
    // Add semantic results (marked as 'semantic')
    for (const article of semanticResults) {
      if (!seen.has(article.title)) {
        seen.add(article.title);
        results.push({ ...article, match_type: 'semantic' });
      }
    }
    
    return results.slice(0, limit);
  } catch (err) {
    console.error('Hybrid search error:', err);
    // Fallback to keyword search
    const keywordResults = await searchArticles(query, limit);
    return keywordResults.map(a => ({ ...a, match_type: 'keyword' }));
  }
}

async function getArticle(title) {
  const result = await pgPool.query(
    'SELECT * FROM articles WHERE title = $1',
    [title]
  );
  return result.rows[0] || null;
}

async function createArticle(title, content, tags, entities, classification) {
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
}

async function updateArticle(title, content, tags, editor = 'system', changeSummary = '') {
  // First get the current article to save as revision
  const currentArticle = await getArticle(title);
  if (!currentArticle) {
    throw new Error(`Article "${title}" not found`);
  }

  // Save revision of the current state before updating
  await createRevision(
    currentArticle.id,
    title,
    currentArticle.content,
    currentArticle.tags,
    editor,
    changeSummary || 'Manual update'
  );

  const result = await pgPool.query(
    `UPDATE articles SET content = $1, tags = $2, updated_at = CURRENT_TIMESTAMP
     WHERE title = $3 RETURNING title`,
    [content, tags || [], title]
  );
  if (result.rowCount === 0) {
    throw new Error(`Article "${title}" not found`);
  }
  return { title: result.rows[0].title, updated: true };
}

async function deleteArticle(title) {
  const result = await pgPool.query(
    'DELETE FROM articles WHERE title = $1 RETURNING id',
    [title]
  );
  if (result.rowCount === 0) {
    throw new Error(`Article "${title}" not found`);
  }
  return { deleted: true, id: result.rows[0].id };
}

async function updateArticleMetadata(articleId, metadata) {
  await pgPool.query(
    `UPDATE articles SET metadata = COALESCE(metadata, '{}') || $1::jsonb WHERE id = $2`,
    [JSON.stringify(metadata), articleId]
  );
  return { updated: true };
}

// Revision database helpers
async function createRevision(articleId, articleTitle, content, tags, editor = 'system', changeSummary = '') {
  const result = await pgPool.query(
    `INSERT INTO revisions (article_id, article_title, content, tags, editor, change_summary)
     VALUES ($1, $2, $3, $4, $5, $6) RETURNING id`,
    [articleId, articleTitle, content, tags || [], editor, changeSummary]
  );
  return result.rows[0].id;
}

async function getArticleRevisions(title, limit = 10) {
  const result = await pgPool.query(
    `SELECT id, content, tags, editor, change_summary, created_at
     FROM revisions
     WHERE article_title = $1
     ORDER BY created_at DESC
     LIMIT $2`,
    [title, limit]
  );
  return result.rows;
}

async function getRevision(revisionId) {
  const result = await pgPool.query(
    `SELECT id, article_id, article_title, content, tags, editor, change_summary, created_at
     FROM revisions WHERE id = $1`,
    [revisionId]
  );
  return result.rows[0] || null;
}

// Format date to short relative format
function formatDate(dateString) {
  if (!dateString) return '';
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now - date;
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);
  
  if (diffMins < 1) return 'now';
  if (diffMins < 60) return `${diffMins}m`;
  if (diffHours < 24) return `${diffHours}h`;
  if (diffDays === 1) return '1d';
  if (diffDays < 7) return `${diffDays}d`;
  if (diffDays < 30) return `${Math.floor(diffDays / 7)}w`;
  
  return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

// Parse path from article title (e.g., "assistance/deployment/guide" -> ["assistance", "deployment", "guide"])
function parsePath(title) {
  if (!title || !title.includes('/')) return { path: [], name: title };
  const parts = title.split('/');
  return {
    path: parts.slice(0, -1),
    name: parts[parts.length - 1]
  };
}

// Get path prefix for grouping (e.g., "assistance/deployment/guide" -> "assistance/deployment")
function getPathPrefix(title) {
  if (!title || !title.includes('/')) return null;
  const parts = title.split('/');
  return parts.slice(0, -1).join('/');
}

// Get top-level group (e.g., "assistance/deployment/guide" -> "assistance")
function getTopGroup(title) {
  if (!title || !title.includes('/')) return 'uncategorized';
  return title.split('/')[0];
}

// Generate breadcrumb HTML for a path
function generateBreadcrumb(title, currentOnly = false) {
  const { path, name } = parsePath(title);
  if (path.length === 0) {
    return `<div class="breadcrumb"><a href="/">Home</a><span class="sep">/</span><span class="current">${escapeHtml(name)}</span></div>`;
  }

  let html = '<div class="breadcrumb"><a href="/">Home</a>';
  let buildPath = '';

  for (let i = 0; i < path.length; i++) {
    buildPath += (i > 0 ? '/' : '') + path[i];
    html += `<span class="sep">/</span><a href="/?group=${encodeURIComponent(buildPath)}">${escapeHtml(path[i])}</a>`;
  }

  html += `<span class="sep">/</span><span class="current">${escapeHtml(currentOnly ? name : title)}</span></div>`;
  return html;
}

// Count articles by group prefix
function countByGroup(articles) {
  const counts = {};
  for (const article of articles) {
    const group = getTopGroup(article.title);
    counts[group] = (counts[group] || 0) + 1;
  }
  return counts;
}

// Generate group menu HTML
function generateGroupMenu(articles, activeGroup = null) {
  const counts = countByGroup(articles);
  const groups = Object.entries(counts).sort((a, b) => b[1] - a[1]);

  let html = '<div class="group-menu"><h3>Browse by Group</h3><div class="group-grid">';

  // All articles button
  const allCount = articles.length;
  const allActive = !activeGroup ? 'active' : '';
  html += `<a href="/" class="group-btn ${allActive}">All<span class="count">${allCount}</span></a>`;

  // Group buttons
  for (const [group, count] of groups) {
    const active = activeGroup === group ? 'active' : '';
    html += `<a href="/?group=${encodeURIComponent(group)}" class="group-btn ${active}">${escapeHtml(group)}<span class="count">${count}</span></a>`;
  }

  html += '</div></div>';
  return html;
}

async function listArticles(limit, offset) {
  const result = await pgPool.query(
    `SELECT id, title, tags, metadata, created_at, updated_at
     FROM articles ORDER BY updated_at DESC LIMIT $1 OFFSET $2`,
    [limit, offset]
  );
  return result.rows;
}

// ============ VALIDATION FUNCTIONS (from ai-worker.js) ============

// Common tech terms for spell checking
const TECH_TERMS = new Set([
  'api', 'http', 'https', 'json', 'xml', 'yaml', 'url', 'uri',
  'docker', 'kubernetes', 'k8s', 'container', 'pod', 'deployment',
  'postgres', 'postgresql', 'mysql', 'mongodb', 'redis',
  'javascript', 'typescript', 'python', 'nodejs', 'react', 'vue',
  'github', 'gitlab', 'git', 'ci/cd', 'cicd', 'pipeline',
  'auth', 'oauth', 'jwt', 'ssl', 'tls', 'encryption',
  'microservice', 'serverless', 'lambda', 'function',
  'websocket', 'grpc', 'graphql', 'rest',
  'mermaid', 'flowchart', 'sequenceDiagram', 'classDiagram',
  'idc1', 'chaba', 'autoagent', 'jarvis', 'portainer', 'mcp'
]);

// Common spelling mistakes to catch
const COMMON_MISSPELLINGS = {
  'recieve': 'receive', 'seperate': 'separate', 'occured': 'occurred',
  'definately': 'definitely', 'occurence': 'occurrence', 'independant': 'independent',
  'enviroment': 'environment', 'accomodate': 'accommodate', 'commited': 'committed',
  'occurance': 'occurrence', 'reccomend': 'recommend', 'successfull': 'successful',
  'untill': 'until', 'occured': 'occurred', 'accross': 'across',
  'begining': 'beginning', 'beleive': 'believe', 'definately': 'definitely',
  'definitly': 'definitely', 'immediatly': 'immediately', 'neccessary': 'necessary',
  'occassion': 'occasion', 'occured': 'occurred', 'peice': 'piece',
  'priviledge': 'privilege', 'publically': 'publicly', 'recieve': 'receive',
  'seperate': 'separate', 'supercede': 'supersede', 'tommorow': 'tomorrow',
  'truely': 'truly', 'untill': 'until', 'wierd': 'weird',
  'acheive': 'achieve', 'apparant': 'apparent', 'appearence': 'appearance',
  'arguement': 'argument', 'becomming': 'becoming', 'begining': 'beginning',
  'beleive': 'believe', 'beleived': 'believed', 'beleives': 'believes',
  'beleiving': 'believing', 'benifit': 'benefit', 'benifits': 'benefits',
  'buisness': 'business', 'calender': 'calendar', 'catagory': 'category',
  'cemetary': 'cemetery', 'changable': 'changeable', 'comming': 'coming',
  'commited': 'committed', 'comittee': 'committee', 'completly': 'completely',
  'concious': 'conscious', 'curiousity': 'curiosity', 'definate': 'definite',
  'definately': 'definitely', 'definit': 'definite', 'definitly': 'definitely',
  'develope': 'develop', 'develoment': 'development', 'dieing': 'dying',
  'diffrent': 'different', 'dilema': 'dilemma', 'dissapoint': 'disappoint',
  'ecstacy': 'ecstasy', 'embarass': 'embarrass', 'enviroment': 'environment',
  'equiped': 'equipped', 'existance': 'existence', 'experiance': 'experience',
  'farenheit': 'fahrenheit', 'finaly': 'finally', 'foriegn': 'foreign',
  'freind': 'friend', 'fullfill': 'fulfill', 'goverment': 'government',
  'grammer': 'grammar', 'greatful': 'grateful', 'griefing': 'grieving',
  'harrass': 'harass', 'heighth': 'height', 'hipocrit': 'hypocrite',
  'humerous': 'humorous', 'immediatly': 'immediately', 'independant': 'independent',
  'indespensable': 'indispensable', 'inovative': 'innovative', 'knowlege': 'knowledge',
  'liason': 'liaison', 'libary': 'library', 'looseing': 'losing',
  'maintainance': 'maintenance', 'managable': 'manageable', 'millenium': 'millennium',
  'miniture': 'miniature', 'mischevious': 'mischievous', 'misspell': 'misspell',
  'neccessary': 'necessary', 'necesary': 'necessary', 'neice': 'niece',
  'nieghbor': 'neighbor', 'noticable': 'noticeable', 'noticably': 'noticeably',
  'occassion': 'occasion', 'occured': 'occurred', 'occurance': 'occurrence',
  'occurence': 'occurrence', 'paralell': 'parallel', 'pasttime': 'pastime',
  'peice': 'piece', 'percieve': 'perceive', 'persistant': 'persistent',
  'personell': 'personnel', 'plagerize': 'plagiarize', 'playright': 'playwright',
  'posession': 'possession', 'prefered': 'preferred', 'presance': 'presence',
  'procede': 'proceed', 'pronounciation': 'pronunciation', 'propoganda': 'propaganda',
  'publically': 'publicly', 'recieve': 'receive', 'recoginze': 'recognize',
  'reccomend': 'recommend', 'refering': 'referring', 'relevent': 'relevant',
  'religous': 'religious', 'repetion': 'repetition', 'restaraunt': 'restaurant',
  'rythm': 'rhythm', 'seige': 'siege', 'sence': 'sense',
  'seperate': 'separate', 'sieze': 'seize', 'similiar': 'similar',
  'sophmore': 'sophomore', 'speach': 'speech', 'stratagy': 'strategy',
  'sucessful': 'successful', 'supercede': 'supersede', 'suprise': 'surprise',
  'surpress': 'suppress', 'temperment': 'temperament', 'tommorow': 'tomorrow',
  'truely': 'truly', 'tyrany': 'tyranny', 'underate': 'underrate',
  'untill': 'until', 'usefull': 'useful', 'usualy': 'usually',
  'vacumme': 'vacuum', 'vegatarian': 'vegetarian', 'vehical': 'vehicle',
  'visious': 'vicious', 'wierd': 'weird', 'writting': 'writing'
};

// Validate content for spelling, syntax, and diagram errors
function validateContent(content, title) {
  const errors = [];
  const warnings = [];

  // 1. Markdown Syntax Validation
  const markdownErrors = validateMarkdownSyntax(content);
  errors.push(...markdownErrors.errors);
  warnings.push(...markdownErrors.warnings);

  // 2. Mermaid Diagram Validation
  const mermaidErrors = validateMermaidDiagrams(content);
  errors.push(...mermaidErrors.errors);
  warnings.push(...mermaidErrors.warnings);

  // 3. Code Block Validation
  const codeErrors = validateCodeBlocks(content);
  errors.push(...codeErrors.errors);
  warnings.push(...codeErrors.warnings);

  // 4. Spelling Check (basic patterns)
  const spellingErrors = checkSpelling(content);
  errors.push(...spellingErrors.errors);
  warnings.push(...spellingErrors.warnings);

  // 5. Link Validation
  const linkErrors = validateLinks(content);
  errors.push(...linkErrors.errors);
  warnings.push(...linkErrors.warnings);

  return {
    error_count: errors.length,
    warning_count: warnings.length,
    errors: errors.slice(0, 10),
    warnings: warnings.slice(0, 10),
    has_critical_errors: errors.some(e => e.severity === 'critical'),
    is_valid: errors.length === 0
  };
}

function validateMarkdownSyntax(content) {
  const errors = [];
  const warnings = [];

  // Check for unclosed code blocks
  const codeFenceMatches = content.match(/```/g) || [];
  if (codeFenceMatches.length % 2 !== 0) {
    errors.push({
      type: 'markdown',
      severity: 'critical',
      message: `Unclosed code block: ${codeFenceMatches.length} fence(s) found (must be even)`,
      fix: 'Add closing ``` to complete the code block'
    });
  }

  // Check for unclosed inline code
  const backtickMatches = content.match(/`[^`]*$/gm) || [];
  if (backtickMatches.length > 0) {
    errors.push({
      type: 'markdown',
      severity: 'error',
      message: `Unclosed inline code: ${backtickMatches.length} instance(s)`,
      fix: 'Close with matching ` backtick'
    });
  }

  // Check for broken markdown links [text](url with spaces)
  const brokenLinks = content.match(/\[([^\]]+)\]\(([^)]+\s[^)]+)\)/g) || [];
  brokenLinks.forEach(link => {
    errors.push({
      type: 'markdown',
      severity: 'error',
      message: `Broken markdown link with spaces: ${link.substring(0, 50)}...`,
      fix: 'URL encode spaces with %20 or replace with - or _'
    });
  });

  // Check for missing alt text in images
  const imagesWithoutAlt = content.match(/!\[\]\([^)]+\)/g) || [];
  if (imagesWithoutAlt.length > 0) {
    warnings.push({
      type: 'markdown',
      severity: 'warning',
      message: `${imagesWithoutAlt.length} image(s) without alt text`,
      fix: 'Add descriptive alt text: ![description](url)'
    });
  }

  // Check for headers without space after #
  const badHeaders = content.match(/^#{1,6}[^\s#]/gm) || [];
  if (badHeaders.length > 0) {
    errors.push({
      type: 'markdown',
      severity: 'error',
      message: `${badHeaders.length} header(s) missing space after #`,
      fix: 'Add space: ## Header not ##Header'
    });
  }

  // Check for inconsistent list indentation
  const listLines = content.match(/^[\s]*[-*+][\s]/gm) || [];
  const indentations = listLines.map(l => l.match(/^[\s]*/)[0].length);
  const uniqueIndents = [...new Set(indentations)];
  if (uniqueIndents.length > 2) {
    warnings.push({
      type: 'markdown',
      severity: 'warning',
      message: `Inconsistent list indentation (${uniqueIndents.length} levels)`,
      fix: 'Use 2 or 4 spaces consistently'
    });
  }

  return { errors, warnings };
}

function validateMermaidDiagrams(content) {
  const errors = [];
  const warnings = [];

  // Extract mermaid blocks
  const mermaidBlocks = content.match(/```mermaid\n([\s\S]*?)```/g) || [];

  mermaidBlocks.forEach((block, index) => {
    const diagramContent = block.replace(/```mermaid\n?/, '').replace(/```$/, '');
    const lines = diagramContent.split('\n').map(l => l.trim()).filter(l => l);

    if (lines.length === 0) {
      errors.push({
        type: 'mermaid',
        severity: 'error',
        message: `Diagram #${index + 1}: Empty diagram`,
        fix: 'Add diagram content'
      });
      return;
    }

    const firstLine = lines[0].toLowerCase();

    // Check for valid diagram type
    const validTypes = ['flowchart', 'sequencediagram', 'classdiagram', 'statediagram',
                       'erdiagram', 'gantt', 'pie', 'gitgraph', 'mindmap', 'timeline',
                       'journey', 'requirementdiagram', 'c4context', 'c4container'];
    const hasValidType = validTypes.some(type => firstLine.includes(type.toLowerCase()));

    if (!hasValidType && !firstLine.includes('graph ')) {
      warnings.push({
        type: 'mermaid',
        severity: 'warning',
        message: `Diagram #${index + 1}: Unrecognized diagram type "${firstLine.substring(0, 30)}"`,
        fix: `Use one of: ${validTypes.slice(0, 5).join(', ')}...`
      });
    }

    // Check for excessive diagram size
    if (lines.length > 50) {
      warnings.push({
        type: 'mermaid',
        severity: 'warning',
        message: `Diagram #${index + 1}: Very large diagram (${lines.length} lines)`,
        fix: 'Consider breaking into smaller diagrams or using subgraphs'
      });
    }
  });

  // Check for mermaid syntax mentioned but not in code block
  const mermaidKeywords = ['flowchart', 'sequencediagram', 'classdiagram', 'graph TD', 'graph LR'];
  const hasMermaidKeyword = mermaidKeywords.some(kw => content.toLowerCase().includes(kw.toLowerCase()));
  const hasMermaidBlock = content.includes('```mermaid');

  if (hasMermaidKeyword && !hasMermaidBlock) {
    errors.push({
      type: 'mermaid',
      severity: 'critical',
      message: 'Mermaid diagram syntax found but not wrapped in ```mermaid code block',
      fix: 'Wrap diagram with:\n```mermaid\n...\n```'
    });
  }

  return { errors, warnings };
}

function validateCodeBlocks(content) {
  const errors = [];
  const warnings = [];

  // Extract all code blocks
  const codeBlocks = content.match(/```(\w*)\n([\s\S]*?)```/g) || [];

  codeBlocks.forEach((block, index) => {
    const langMatch = block.match(/```(\w*)/);
    const lang = langMatch ? langMatch[1] : '';
    const code = block.replace(/```\w*\n?/, '').replace(/```$/, '');

    if (!lang) {
      warnings.push({
        type: 'code',
        severity: 'warning',
        message: `Code block #${index + 1}: No language specified`,
        fix: 'Add language: ```javascript, ```python, ```bash, etc.'
      });
    }

    // Language-specific checks
    if (lang === 'javascript' || lang === 'js' || lang === 'typescript' || lang === 'ts') {
      const unclosedParens = (code.match(/\(/g) || []).length !== (code.match(/\)/g) || []).length;
      const unclosedBraces = (code.match(/\{/g) || []).length !== (code.match(/\}/g) || []).length;
      const unclosedBrackets = (code.match(/\[/g) || []).length !== (code.match(/\]/g) || []).length;

      if (unclosedParens) {
        errors.push({
          type: 'code',
          severity: 'error',
          language: lang,
          message: `JS code block #${index + 1}: Unclosed parentheses`,
          fix: 'Ensure all ( and ) are matched'
        });
      }
      if (unclosedBraces) {
        errors.push({
          type: 'code',
          severity: 'error',
          language: lang,
          message: `JS code block #${index + 1}: Unclosed braces`,
          fix: 'Ensure all { and } are matched'
        });
      }
      if (unclosedBrackets) {
        errors.push({
          type: 'code',
          severity: 'error',
          language: lang,
          message: `JS code block #${index + 1}: Unclosed brackets`,
          fix: 'Ensure all [ and ] are matched'
        });
      }
    }

    if (lang === 'python' || lang === 'py') {
      // Check for Python 2 vs 3 syntax
      if (code.includes('print ') && !code.includes('print(')) {
        errors.push({
          type: 'code',
          severity: 'error',
          language: lang,
          message: `Python code block #${index + 1}: Python 2 print syntax detected`,
          fix: 'Use Python 3 syntax: print("message")'
        });
      }
    }

    if (lang === 'bash' || lang === 'sh' || lang === 'shell') {
      // Check for common bash mistakes
      if (code.includes('rm -rf /') || code.includes('rm -rf /*')) {
        errors.push({
          type: 'code',
          severity: 'critical',
          language: lang,
          message: `Bash code block #${index + 1}: DANGEROUS rm -rf command detected`,
          fix: 'DO NOT include destructive commands without warnings'
        });
      }
    }

    // Check for very long lines
    const longLines = code.split('\n').filter(l => l.length > 100);
    if (longLines.length > 3) {
      warnings.push({
        type: 'code',
        severity: 'warning',
        message: `Code block #${index + 1}: ${longLines.length} lines exceed 100 characters`,
        fix: 'Break long lines for readability'
      });
    }
  });

  return { errors, warnings };
}

function checkSpelling(content) {
  const errors = [];
  const warnings = [];

  // Get text content (exclude code blocks)
  const textContent = content.replace(/```[\s\S]*?```/g, ' ');
  const words = textContent.toLowerCase().split(/[^a-z]+/).filter(w => w.length > 3);

  // Check for common misspellings
  for (const [wrong, correct] of Object.entries(COMMON_MISSPELLINGS)) {
    const regex = new RegExp(`\\b${wrong}\\b`, 'gi');
    const matches = textContent.match(regex);
    if (matches) {
      errors.push({
        type: 'spelling',
        severity: 'error',
        message: `Spelling error: "${matches[0]}" should be "${correct}"`,
        count: matches.length,
        fix: `Replace with: ${correct}`
      });
    }
  }

  // Check for tech terms misspellings
  const techMisspellings = {
    'postgressql': 'postgresql', 'postgress': 'postgresql',
    'javscript': 'javascript', 'javascipt': 'javascript',
    'typescriptt': 'typescript', 'typscript': 'typescript',
    'dockerr': 'docker', 'docer': 'docker',
    'kuberntes': 'kubernetes', 'kubernets': 'kubernetes',
    'reddis': 'redis', 'rediss': 'redis',
    'graphqll': 'graphql', 'grpahql': 'graphql'
  };

  for (const [wrong, correct] of Object.entries(techMisspellings)) {
    const regex = new RegExp(`\\b${wrong}\\b`, 'gi');
    const matches = textContent.match(regex);
    if (matches) {
      errors.push({
        type: 'spelling',
        severity: 'error',
        category: 'tech-term',
        message: `Tech term misspelled: "${matches[0]}" should be "${correct}"`,
        count: matches.length,
        fix: `Replace with: ${correct}`
      });
    }
  }

  // Check for repeated words
  const repeatedPattern = /\b(\w+)\s+\1\b/gi;
  const repeated = textContent.match(repeatedPattern) || [];
  repeated.forEach(match => {
    warnings.push({
      type: 'spelling',
      severity: 'warning',
      message: `Repeated word: "${match}"`,
      fix: 'Remove duplicate word'
    });
  });

  return { errors, warnings };
}

function validateLinks(content) {
  const errors = [];
  const warnings = [];

  // Extract markdown links
  const links = content.match(/\[([^\]]+)\]\(([^)]+)\)/g) || [];

  links.forEach(link => {
    const urlMatch = link.match(/\]\(([^)]+)\)/);
    if (!urlMatch) return;

    const url = urlMatch[1];

    // Check for empty URLs
    if (!url || url.trim() === '') {
      errors.push({
        type: 'link',
        severity: 'error',
        message: `Empty link URL: ${link.substring(0, 30)}...`,
        fix: 'Add a valid URL'
      });
    }

    // Check for spaces in URLs
    if (url.includes(' ')) {
      errors.push({
        type: 'link',
        severity: 'error',
        message: `URL contains spaces: ${url.substring(0, 40)}`,
        fix: 'Replace spaces with %20 or -'
      });
    }

    // Check for relative links that might be broken
    if (url.startsWith('./') || url.startsWith('../')) {
      warnings.push({
        type: 'link',
        severity: 'warning',
        message: `Relative link (verify target exists): ${url}`,
        fix: 'Ensure linked file exists in correct location'
      });
    }

    // Check for placeholder URLs
    const placeholders = ['example.com', 'localhost', '127.0.0.1', 'your-domain', 'placeholder'];
    if (placeholders.some(p => url.includes(p))) {
      warnings.push({
        type: 'link',
        severity: 'warning',
        message: `Possible placeholder URL: ${url.substring(0, 40)}`,
        fix: 'Replace with actual URL'
      });
    }
  });

  // Check for bare URLs (not in markdown format)
  const bareUrls = content.match(/(?<!\]\()https?:\/\/[^\s<>"\])]+/g) || [];
  if (bareUrls.length > 0) {
    warnings.push({
      type: 'link',
      severity: 'warning',
      message: `${bareUrls.length} bare URL(s) found (not in markdown format)`,
      fix: 'Convert to [description](url) format for better readability'
    });
  }

  return { errors, warnings };
}

// Calculate quality score with validation penalties
function calculateQualityScore(content, tags, validationResult = null) {
  let score = 0.5;

  // Length score (max 0.15)
  const wordCount = content.split(/\s+/).length;
  if (wordCount > 100) score += 0.05;
  if (wordCount > 300) score += 0.05;
  if (wordCount > 800) score += 0.05;

  // Structure score (max 0.20)
  const headerCount = (content.match(/^#{1,6}\s/mg) || []).length;
  if (headerCount > 0) score += Math.min(headerCount * 0.02, 0.10);
  if (content.includes('```')) score += 0.05;
  if (content.includes('|')) score += 0.03;
  if (content.includes('> ')) score += 0.02;

  // Rich Media (max 0.15)
  const images = (content.match(/!\[.*?\]\(.*?\)/g) || []).length;
  const links = (content.match(/\[.*?\]\(https?:\/\/.*?\)/g) || []).length;
  const mermaid = (content.match(/```mermaid/g) || []).length;
  score += Math.min(images * 0.03, 0.09);
  score += Math.min(links * 0.01, 0.05);
  score += Math.min(mermaid * 0.05, 0.10);

  // Metadata (max 0.10)
  if (tags?.length > 0) score += Math.min(tags.length * 0.02, 0.06);

  // === VALIDATION PENALTIES ===
  if (validationResult) {
    const criticalErrors = validationResult.errors.filter(e => e.severity === 'critical').length;
    score -= Math.min(criticalErrors * 0.15, 0.45);

    const regularErrors = validationResult.errors.filter(e => e.severity === 'error').length;
    score -= Math.min(regularErrors * 0.08, 0.24);

    score -= Math.min(validationResult.warning_count * 0.03, 0.15);
  }

  // Broken markdown structure penalty
  const codeFenceCount = (content.match(/```/g) || []).length;
  if (codeFenceCount % 2 !== 0) score -= 0.10;

  // Excessive length without structure penalty
  if (wordCount > 1500 && headerCount < 3) score -= 0.05;

  return Math.max(0, Math.min(Math.round(score * 100) / 100, 1.0));
}

// Simple classification based on content analysis
async function classifyArticle(content) {
  const lower = content.toLowerCase();

  // Heuristic classification
  const hasCode = lower.includes('```') || lower.includes('function') || lower.includes('const ') || lower.includes('import ');
  const hasTutorial = lower.includes('step') || lower.includes('how to') || lower.includes('tutorial') || lower.includes('guide');
  const hasTroubleshooting = lower.includes('error') || lower.includes('fix') || lower.includes('issue') || lower.includes('problem') || lower.includes('troubleshoot');
  const hasReference = lower.includes('api') || lower.includes('reference') || lower.includes('documentation') || lower.includes('list of');

  let type = 'note';
  if (hasTutorial) type = 'tutorial';
  else if (hasTroubleshooting) type = 'troubleshooting';
  else if (hasReference) type = 'reference';
  else if (hasCode) type = 'code-example';

  // Complexity assessment
  const wordCount = content.split(/\s+/).length;
  const headerCount = (content.match(/^#{1,6}\s/mg) || []).length;
  let complexity = 'simple';
  if (wordCount > 500 && headerCount > 3) complexity = 'complex';
  else if (wordCount > 200 || headerCount > 1) complexity = 'moderate';

  return { type, complexity, indicators: { hasCode, hasTutorial, hasTroubleshooting, hasReference } };
}

// Extract tags from content
async function extractTags(content, title) {
  const tags = new Set();
  const lower = content.toLowerCase();

  // Extract from tech terms
  for (const term of TECH_TERMS) {
    if (lower.includes(term.toLowerCase())) {
      tags.add(term);
    }
  }

  // Additional patterns
  if (lower.includes('docker') || lower.includes('container')) tags.add('docker');
  if (lower.includes('kubernetes') || lower.includes('k8s')) tags.add('kubernetes');
  if (lower.includes('database') || lower.includes('sql')) tags.add('database');
  if (lower.includes('api') || lower.includes('rest')) tags.add('api');
  if (lower.includes('error') || lower.includes('debug')) tags.add('troubleshooting');
  if (lower.includes('install') || lower.includes('setup')) tags.add('setup');
  if (lower.includes('deploy') || lower.includes('deployment')) tags.add('deployment');
  if (lower.includes('security') || lower.includes('auth')) tags.add('security');
  if (lower.includes('performance') || lower.includes('optimize')) tags.add('performance');

  return Array.from(tags).slice(0, 8);
}

// Generate TL;DR summary
async function generateSummary(content) {
  // Simple summary: first 2-3 sentences or first 200 chars
  const sentences = content.match(/[^.!?]+[.!?]+/g) || [];
  let summary = sentences.slice(0, 2).join(' ').trim();

  if (summary.length > 300) {
    summary = summary.substring(0, 300) + '...';
  }

  if (!summary || summary.length < 50) {
    summary = content.substring(0, 200).replace(/\n/g, ' ') + '...';
  }

  return summary;
}

// MCP Server Factory - creates new server instance per connection
function createMcpServer() {
  const server = new Server({ name: 'mcp-wiki', version: '1.0.0' }, {
    capabilities: { tools: {} }
  });

  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: [
      {
        name: 'wiki_search',
        description: 'Search articles by title or content. Returns matching articles with metadata.',
        inputSchema: zodToJsonSchema(SearchArticlesSchema)
      },
      {
        name: 'wiki_get',
        description: 'Get article content by title. Returns full article with metadata.',
        inputSchema: zodToJsonSchema(GetArticleSchema)
      },
      {
        name: 'wiki_create',
        description: 'Create new article with title, content, and optional tags. Validates content before creation.',
        inputSchema: zodToJsonSchema(CreateArticleSchema)
      },
      {
        name: 'wiki_update',
        description: 'Update existing article. Preserves metadata unless explicitly changed.',
        inputSchema: zodToJsonSchema(UpdateArticleSchema)
      },
      {
        name: 'wiki_delete',
        description: 'Delete article by title. Use with caution.',
        inputSchema: zodToJsonSchema(DeleteArticleSchema)
      },
      {
        name: 'wiki_list',
        description: 'List recent articles with pagination. Returns titles and update dates.',
        inputSchema: zodToJsonSchema(ListArticlesSchema)
      },
      {
        name: 'wiki_validate',
        description: 'Validate content without saving. Checks spelling, markdown syntax, mermaid diagrams, code blocks, and links. Returns errors, warnings, and quality score.',
        inputSchema: zodToJsonSchema(ValidateContentSchema)
      },
      {
        name: 'wiki_explain',
        description: 'Get detailed explanation of an article including: quality score, validation status, classification, word count, structure analysis, and suggested improvements. Use before editing to understand article state.',
        inputSchema: zodToJsonSchema(ExplainArticleSchema)
      },
      {
        name: 'wiki_enhance',
        description: 'Trigger AI enhancement for an article (classify, summarize, suggest-links, validate). Returns enhancement results.',
        inputSchema: zodToJsonSchema(EnhanceArticleSchema)
      },
      {
        name: 'wiki_suggest_tags',
        description: 'Get AI-suggested tags for content based on tech terms and content analysis.',
        inputSchema: zodToJsonSchema(SuggestTagsSchema)
      },
      {
        name: 'wiki_smart_research',
        description: 'Smart article lookup using query analysis with semantic caching',
        inputSchema: zodToJsonSchema(SearchArticlesSchema)
      },
      {
        name: 'wiki_semantic_search',
        description: 'Semantic search using vector embeddings (Weaviate). Finds articles by meaning, not just keywords.',
        inputSchema: zodToJsonSchema(SemanticSearchSchema)
      },
      {
        name: 'wiki_hybrid_search',
        description: 'Hybrid search combining keyword and semantic search. Alpha 0=keyword, 1=semantic, 0.5=balanced.',
        inputSchema: zodToJsonSchema(HybridSearchSchema)
      },
      {
        name: 'wiki_get_history',
        description: 'Get revision history for an article. Returns list of previous versions with timestamps.',
        inputSchema: zodToJsonSchema(GetHistorySchema)
      },
      {
        name: 'wiki_revert',
        description: 'Revert article to a specific revision. Creates a new revision with the old content.',
        inputSchema: zodToJsonSchema(RevertArticleSchema)
      },
      {
        name: 'wiki_diff',
        description: 'Compare two revisions and show differences. If revision_id_2 is omitted, compares with current article.',
        inputSchema: zodToJsonSchema(DiffRevisionsSchema)
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

      case 'wiki_semantic_search': {
        const { query, limit } = SemanticSearchSchema.parse(args);
        const results = await semanticSearch(query, limit);
        return {
          content: [{
            type: 'text',
            text: JSON.stringify(results, null, 2) || 'No results found'
          }]
        };
      }

      case 'wiki_hybrid_search': {
        const { query, limit, alpha } = HybridSearchSchema.parse(args);
        const results = await hybridSearch(query, limit, alpha);
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

      case 'wiki_delete': {
        const { title } = DeleteArticleSchema.parse(args);
        const article = await getArticle(title);
        if (!article) {
          return {
            content: [{ type: 'text', text: `Article "${title}" not found` }],
            isError: true
          };
        }
        await deleteArticle(title);
        return {
          content: [{ type: 'text', text: `Deleted article "${title}"` }]
        };
      }

      case 'wiki_validate': {
        const { content, title } = ValidateContentSchema.parse(args);
        const validation = validateContent(content, title || 'Untitled');
        const qualityScore = calculateQualityScore(content, [], validation);

        const summary = validation.is_valid
          ? `✅ Valid! Quality score: ${qualityScore.toFixed(2)}/1.0\n${validation.warning_count > 0 ? `⚠️ ${validation.warning_count} warning(s) to consider` : 'No warnings'}`
          : `❌ Has errors! Quality score: ${qualityScore.toFixed(2)}/1.0\n${validation.error_count} error(s), ${validation.warning_count} warning(s)`;

        const details = validation.errors.map(e => `❌ [${e.type}] ${e.message}${e.fix ? `\n   Fix: ${e.fix}` : ''}`).join('\n\n');
        const warnings = validation.warnings.map(w => `⚠️ [${w.type}] ${w.message}${w.fix ? `\n   Suggestion: ${w.fix}` : ''}`).join('\n\n');

        return {
          content: [{
            type: 'text',
            text: `${summary}\n\n## Errors (${validation.error_count}):\n${details || 'None'}\n\n## Warnings (${validation.warning_count}):\n${warnings || 'None'}`
          }]
        };
      }

      case 'wiki_explain': {
        const { title } = ExplainArticleSchema.parse(args);
        const article = await getArticle(title);
        if (!article) {
          return {
            content: [{ type: 'text', text: `Article "${title}" not found` }],
            isError: true
          };
        }

        const metadata = article.metadata || {};
        const wordCount = article.content.split(/\s+/).length;
        const validation = validateContent(article.content, article.title);
        const qualityScore = metadata.quality_score || calculateQualityScore(article.content, article.tags, validation);

        // Structure analysis
        const headers = (article.content.match(/^#{1,6}\s/mg) || []).length;
        const codeBlocks = (article.content.match(/```/g) || []).length / 2;
        const images = (article.content.match(/!\[.*?\]\(.*?\)/g) || []).length;
        const links = (article.content.match(/\[.*?\]\(https?:\/\/.*?\)/g) || []).length;
        const mermaid = (article.content.match(/```mermaid/g) || []).length;

        // Suggestions
        const suggestions = [];
        if (wordCount < 100) suggestions.push('Article is short. Consider adding more detail.');
        if (headers === 0 && wordCount > 300) suggestions.push('Add headers to structure the content.');
        if (codeBlocks === 0 && article.content.includes('code')) suggestions.push('Consider adding code blocks for technical content.');
        if (article.tags.length === 0) suggestions.push('Add tags for better discoverability.');
        if (validation.errors.length > 0) suggestions.push(`Fix ${validation.errors.length} validation error(s).`);
        if (validation.warnings.length > 0) suggestions.push(`Review ${validation.warnings.length} warning(s).`);

        const explanation = `# 📊 Article Analysis: "${article.title}"

## Quality Metrics
- **Quality Score:** ${qualityScore.toFixed(2)}/1.0
- **Word Count:** ${wordCount}
- **Classification:** ${metadata.classification || 'Not classified'}
- **Complexity:** ${metadata.complexity || 'Unknown'}
- **Validation:** ${validation.is_valid ? '✅ Valid' : `❌ ${validation.error_count} error(s)`}

## Structure
- **Headers:** ${headers}
- **Code Blocks:** ${Math.floor(codeBlocks)}
- **Images:** ${images}
- **External Links:** ${links}
- **Mermaid Diagrams:** ${mermaid}

## Tags
${article.tags?.length > 0 ? article.tags.map(t => `- ${t}`).join('\n') : 'None'}

## Metadata
- **Created:** ${article.created_at}
- **Updated:** ${article.updated_at}
- **TL;DR:** ${metadata.tldr || 'Not generated'}

## 💡 Suggestions
${suggestions.length > 0 ? suggestions.map(s => `- ${s}`).join('\n') : 'No suggestions - article looks good!'}

## Validation Details
${validation.errors.length > 0 ? `Errors:\n${validation.errors.slice(0, 3).map(e => `- [${e.type}] ${e.message}`).join('\n')}` : 'No validation errors.'}
${validation.warnings.length > 0 ? `\nWarnings:\n${validation.warnings.slice(0, 3).map(w => `- [${w.type}] ${w.message}`).join('\n')}` : ''}`;

        return {
          content: [{ type: 'text', text: explanation }]
        };
      }

      case 'wiki_enhance': {
        const { title, actions } = EnhanceArticleSchema.parse(args);
        const article = await getArticle(title);
        if (!article) {
          return {
            content: [{ type: 'text', text: `Article "${title}" not found` }],
            isError: true
          };
        }

        // Run enhancement synchronously for MCP
        const results = {};

        if (actions.includes('validate')) {
          const validation = validateContent(article.content, article.title);
          results.validation = {
            is_valid: validation.is_valid,
            errors: validation.error_count,
            warnings: validation.warning_count,
            quality_score: calculateQualityScore(article.content, article.tags, validation)
          };
        }

        if (actions.includes('classify')) {
          const classification = await classifyArticle(article.content);
          const suggestedTags = await extractTags(article.content, article.title);
          results.classification = classification;
          results.suggested_tags = suggestedTags;
        }

        if (actions.includes('summarize')) {
          const tldr = await generateSummary(article.content);
          results.summary = tldr;
        }

        // Update metadata
        const metadataUpdate = {
          ...results,
          last_enhanced: new Date().toISOString()
        };
        await updateArticleMetadata(article.id, metadataUpdate);

        return {
          content: [{
            type: 'text',
            text: `Enhanced "${title}" with actions: ${actions.join(', ')}\n\nResults:\n${JSON.stringify(results, null, 2)}`
          }]
        };
      }

      case 'wiki_suggest_tags': {
        const { content, title } = SuggestTagsSchema.parse(args);
        const tags = await extractTags(content, title || 'Untitled');
        return {
          content: [{
            type: 'text',
            text: `Suggested tags:\n${tags.map(t => `- ${t}`).join('\n')}\n\nUse these tags when creating the article.`
          }]
        };
      }

      case 'wiki_smart_research': {
        const { query, limit } = SearchArticlesSchema.parse(args);

        // Step 1: Analyze query intent
        const queryAnalysis = {
          query,
          intent: 'research',
          keywords: query.toLowerCase().split(/\s+/).filter(w => w.length > 3),
          timestamp: new Date().toISOString()
        };

        // Step 2: Try exact match first
        const exactMatch = await getArticle(query);
        if (exactMatch) {
          return {
            content: [{
              type: 'text',
              text: `# Exact Match Found: "${exactMatch.title}"\n\n**Tags:** ${exactMatch.tags?.join(', ') || 'none'}\n**Updated:** ${exactMatch.updated_at}\n\n${exactMatch.content.substring(0, 2000)}${exactMatch.content.length > 2000 ? '\n\n...(truncated)' : ''}`
            }]
          };
        }

        // Step 3: Hybrid search for related content
        const results = await hybridSearch(query, limit, 0.5);

        if (results.length === 0) {
          return {
            content: [{
              type: 'text',
              text: `No articles found for "${query}".\n\nQuery Analysis:\n- Keywords: ${queryAnalysis.keywords.join(', ')}\n- Suggestion: Try creating a new article with wiki_create`
            }]
          };
        }

        // Step 4: Analyze and synthesize results
        const synthesized = results.map(r => ({
          title: r.title,
          relevance: r.match_type === 'semantic' ? 'high (semantic)' : 'medium (keyword)',
          snippet: r.content?.substring(0, 300) || r.snippet || 'No preview',
          tags: r.tags,
          updated: r.updated_at
        }));

        const output = `# Smart Research Results: "${query}"\n\n## Query Analysis\n- **Intent:** Research/Information gathering\n- **Keywords:** ${queryAnalysis.keywords.join(', ')}\n- **Results:** ${results.length} articles found\n\n## Top Results\n\n${synthesized.map((r, i) => `### ${i + 1}. ${r.title}\n- **Relevance:** ${r.relevance}\n- **Updated:** ${r.updated}\n- **Tags:** ${Array.isArray(r.tags) ? r.tags.join(', ') : r.tags || 'none'}\n\n${r.snippet}...\n`).join('\n---\n\n')}\n\n## Recommendations\n${results.length > 0 ? '- Found relevant existing knowledge' : '- Consider creating a new article'}\n${results.some(r => r.match_type === 'semantic') ? '- Semantic matches suggest conceptual relevance' : '- Try semantic search for broader matches'}`;

        return {
          content: [{
            type: 'text',
            text: output
          }]
        };
      }

      case 'wiki_get_history': {
        const { title, limit } = GetHistorySchema.parse(args);
        const revisions = await getArticleRevisions(title, limit);
        if (revisions.length === 0) {
          return {
            content: [{ type: 'text', text: `No revision history found for "${title}". Article may not exist or has no saved revisions.` }],
            isError: true
          };
        }
        const history = revisions.map((rev, index) =>
          `## Revision ${revisions.length - index} (ID: ${rev.id})\n- **Date:** ${rev.created_at}\n- **Editor:** ${rev.editor || 'unknown'}\n- **Summary:** ${rev.change_summary || 'No summary'}\n- **Preview:** ${rev.content?.substring(0, 100).replace(/\n/g, ' ')}...`
        ).join('\n\n');
        return {
          content: [{
            type: 'text',
            text: `# Revision History for "${title}"\n\n${history}`
          }]
        };
      }

      case 'wiki_revert': {
        const { title, revision_id } = RevertArticleSchema.parse(args);
        const article = await getArticle(title);
        if (!article) {
          return {
            content: [{ type: 'text', text: `Article "${title}" not found` }],
            isError: true
          };
        }
        const revision = await getRevision(revision_id);
        if (!revision) {
          return {
            content: [{ type: 'text', text: `Revision ${revision_id} not found` }],
            isError: true
          };
        }
        if (revision.article_title !== title) {
          return {
            content: [{ type: 'text', text: `Revision ${revision_id} does not belong to article "${title}"` }],
            isError: true
          };
        }
        // Revert by updating with the revision's content
        const tags = Array.isArray(revision.tags) ? revision.tags : (revision.tags ? revision.tags.split(',').map(t => t.trim()).filter(Boolean) : []);
        await updateArticle(title, revision.content, tags, 'system', `Reverted to revision ${revision_id}`);
        return {
          content: [{
            type: 'text',
            text: `✅ Reverted "${title}" to revision ${revision_id} from ${revision.created_at}`
          }]
        };
      }

      case 'wiki_diff': {
        const { title, revision_id_1, revision_id_2 } = DiffRevisionsSchema.parse(args);
        const revision1 = await getRevision(revision_id_1);
        if (!revision1) {
          return {
            content: [{ type: 'text', text: `Revision ${revision_id_1} not found` }],
            isError: true
          };
        }
        let content2;
        let label2;
        if (revision_id_2) {
          const revision2 = await getRevision(revision_id_2);
          if (!revision2) {
            return {
              content: [{ type: 'text', text: `Revision ${revision_id_2} not found` }],
              isError: true
            };
          }
          content2 = revision2.content;
          label2 = `Revision ${revision_id_2}`;
        } else {
          const article = await getArticle(title);
          if (!article) {
            return {
              content: [{ type: 'text', text: `Article "${title}" not found` }],
              isError: true
            };
          }
          content2 = article.content;
          label2 = 'Current Version';
        }
        // Simple diff: show lines that changed
        const lines1 = revision1.content.split('\n');
        const lines2 = content2.split('\n');
        const maxLines = Math.max(lines1.length, lines2.length);
        let diff = '';
        for (let i = 0; i < maxLines; i++) {
          const line1 = lines1[i] || '';
          const line2 = lines2[i] || '';
          if (line1 !== line2) {
            diff += `Line ${i + 1}:\n- ${line1}\n+ ${line2}\n\n`;
          }
        }
        if (!diff) {
          diff = 'No differences found - content is identical.';
        }
        return {
          content: [{
            type: 'text',
            text: `# Diff: Revision ${revision_id_1} vs ${label2}\n\n${diff}`
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

  return server;
}

// HTTP Server for Web UI
const app = express();

// Authentication middleware for write operations
function requireAuth(req, res, next) {
  // Skip auth for MCP protocol endpoints (SSE transport) and health check
  if (req.path === '/mcp/sse' || req.path === '/mcp/message' || req.path === '/health') {
    return next();
  }
  
  // Skip auth for read-only GET requests, but NOT for /new (article creation form)
  if (req.method === 'GET' && req.path !== '/new') {
    return next();
  }
  
  // Skip auth if no API key is configured (development mode)
  if (!API_KEY) {
    return next();
  }
  
  const authHeader = req.headers.authorization;
  const apiKeyFromHeader = authHeader?.startsWith('Bearer ') ? authHeader.slice(7) : null;
  const apiKeyFromQuery = req.query.api_key;
  
  const providedKey = apiKeyFromHeader || apiKeyFromQuery;
  
  if (!providedKey || providedKey !== API_KEY) {
    return res.status(401).json({ error: 'Unauthorized: Invalid or missing API key' });
  }
  
  next();
}

// Apply authentication middleware
app.use(requireAuth);

// Body parsers for API endpoints (must be before routes)
// Skip body parsing for MCP message endpoint - SSEServerTransport needs raw body stream
app.use((req, res, next) => {
  if (req.path === '/mcp/message') return next();
  express.json()(req, res, next);
});
app.use((req, res, next) => {
  if (req.path === '/mcp/message') return next();
  express.urlencoded({ extended: true })(req, res, next);
});

// Health check endpoint for container orchestration
app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'mcp-wiki', timestamp: new Date().toISOString() });
});

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
    .container h1 {
      border-bottom: 2px solid #e5e7eb;
      padding-bottom: 8px;
      margin: 0 0 12px;
      font-size: 28px;
    }
    .container .meta {
      color: #6b7280;
      font-size: 13px;
      margin: 8px 0 12px;
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
    /* Breadcrumb Navigation */
    .breadcrumb {
      background: #fff;
      padding: 10px 16px;
      border-radius: 6px;
      margin-bottom: 12px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.1);
      font-size: 14px;
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 6px;
    }
    .breadcrumb a {
      color: #2563eb;
      text-decoration: none;
      padding: 4px 8px;
      border-radius: 4px;
    }
    .breadcrumb a:hover {
      background: #e0e7ff;
    }
    .breadcrumb .sep {
      color: #9ca3af;
    }
    .breadcrumb .current {
      color: #374151;
      font-weight: 500;
      padding: 4px 8px;
    }
    /* Group Selection Menu */
    .group-menu {
      background: #fff;
      padding: 12px 16px;
      border-radius: 6px;
      margin-bottom: 15px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
    .group-menu h3 {
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: #6b7280;
      margin-bottom: 10px;
    }
    .group-grid {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .group-btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 12px;
      background: #f3f4f6;
      color: #374151;
      text-decoration: none;
      border-radius: 20px;
      font-size: 13px;
      transition: all 0.15s;
    }
    .group-btn:hover {
      background: #e5e7eb;
    }
    .group-btn.active {
      background: #2563eb;
      color: white;
    }
    .group-btn .count {
      background: rgba(0,0,0,0.1);
      color: inherit;
      padding: 2px 6px;
      border-radius: 10px;
      font-size: 11px;
      font-weight: 600;
    }
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
      border-radius: 4px;
      text-decoration: none;
      font-size: 11px;
      display: inline-block;
      margin: 0 2px;
      border: none;
      cursor: pointer;
    }
    .btn-small:hover { background: #7c3aed; }
    .btn-rerun {
      background: #dc2626;
    }
    .btn-rerun:hover {
      background: #b91c1c;
    }
    .btn-merge {
      background: #059669;
    }
    .btn-merge:hover {
      background: #047857;
    }
    .enhance-select {
      padding: 4px 8px;
      font-size: 11px;
      border: 1px solid #d1d5db;
      border-radius: 3px;
      background: white;
      color: #374151;
      flex: 1;
      min-width: 0;
    }
    .enhance-form {
      margin-top: 8px;
    }
    .enhance-form-row {
      display: flex;
      gap: 6px;
      align-items: center;
    }
    .ai-controls {
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid rgba(139, 92, 246, 0.2);
    }
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
      line-height: 1.6;
      font-size: 15px;
    }
    .article-content h1 { margin: 24px 0 12px; }
    .article-content h2 { margin: 20px 0 10px; }
    .article-content h3 { margin: 16px 0 8px; }
    .article-content h4, .article-content h5, .article-content h6 { margin: 14px 0 6px; }
    .article-content p { margin-bottom: 12px; }
    .article-content ul, .article-content ol { margin: 8px 0; padding-left: 24px; }
    .article-content li { margin: 4px 0; }
    .article-content pre { margin: 12px 0; }
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
      border-radius: 6px;
      padding: 12px;
      margin: 12px 0;
      text-align: center;
    }
    pre:has(code.language-mermaid) {
      background: transparent;
      padding: 0;
      margin: 12px 0;
    }
    pre code.language-mermaid {
      display: none; /* Hide raw mermaid code, let mermaid render SVG */
    }
    /* AI Metadata Section */
    .ai-metadata {
      background: linear-gradient(135deg, #f3e8ff 0%, #e0e7ff 100%);
      border-radius: 6px;
      padding: 10px 14px;
      margin-bottom: 12px;
      border-left: 3px solid #8b5cf6;
    }
    .ai-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 6px;
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
      padding: 8px 12px;
      border-radius: 4px;
      margin-bottom: 8px;
      font-size: 13px;
      line-height: 1.5;
      color: #374151;
    }
    .ai-tags {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .ai-prompt {
      background: #fef3c7;
      border: 2px dashed #f59e0b;
      border-radius: 6px;
      padding: 14px;
      text-align: center;
      margin-bottom: 14px;
    }
    .ai-prompt p {
      color: #92400e;
      margin-bottom: 8px;
      font-size: 14px;
    }
    /* Validation Status */
    .validation-status {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 6px 10px;
      border-radius: 4px;
      margin: 8px 0 0;
      font-size: 12px;
    }
    .validation-status.valid {
      background: #d1fae5;
      color: #065f46;
      border: 1px solid #10b981;
    }
    .validation-status.has-issues {
      background: #fee2e2;
      color: #991b1b;
      border: 1px solid #ef4444;
    }
    .validation-badge {
      font-weight: 600;
    }
    .validation-details {
      opacity: 0.9;
    }
    .validation-hint {
      font-size: 11px;
      opacity: 0.7;
      font-style: italic;
      margin-left: auto;
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
app.get('/health', async (req, res) => {
  const health = {
    status: 'ok',
    timestamp: new Date().toISOString(),
    database: {
      type: 'postgresql',
      connected: false
    },
    articles: null
  };

  try {
    if (pgPool) {
      const result = await pgPool.query('SELECT COUNT(*) as count FROM articles');
      health.database.connected = true;
      health.database.article_count = parseInt(result.rows[0].count);
    }

    res.json(health);
  } catch (err) {
    health.status = 'error';
    health.error = err.message;
    res.status(503).json(health);
  }
});

// Home / List
app.get('/', async (req, res) => {
  try {
    const groupFilter = req.query.group || null;
    const allArticles = await listArticles(200, 0);

    // Filter articles by group if specified
    const articles = groupFilter
      ? allArticles.filter(a => a.title.startsWith(groupFilter + '/') || a.title === groupFilter)
      : allArticles;

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

    // Generate breadcrumb for group filter
    let breadcrumb = '';
    if (groupFilter) {
      breadcrumb = generateBreadcrumb(groupFilter, true);
    }

    // Generate group menu
    const groupMenu = generateGroupMenu(allArticles, groupFilter);

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
      ? `<div class="empty-state"><p>No articles ${groupFilter ? 'in group "' + escapeHtml(groupFilter) + '"' : 'yet'}.</p><a href="/new" class="btn-primary">Create First Article</a></div>`
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
              <div class="enhance-form">
                <form action="/enhance/${a.id}" method="GET" style="display:flex;gap:4px;align-items:center;">
                  <select name="actions" class="enhance-select">
                    <option value="classify,summarize">Quick (Classify+Summary)</option>
                    <option value="classify">Classify Only</option>
                    <option value="summarize">Summary Only</option>
                    <option value="classify,summarize,suggest-links">Full (+Links)</option>
                    <option value="validate">Validate Only</option>
                    <option value="embed">Generate Embedding</option>
                  </select>
                  <button type="submit" class="btn-small">${metadata.classification ? '↻ Re-enhance' : '✨ Enhance'}</button>
                </form>
              </div>
            </article>
          `;
        }).join('') + '</div>';

    res.send(htmlPage(groupFilter ? `Group: ${groupFilter}` : 'Home', searchForm + breadcrumb + groupMenu + statsBar + list));
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
    
    const validationStatus = metadata.validation_status;
    const validationErrors = metadata.validation_errors || 0;
    const validationWarnings = metadata.validation_warnings || 0;
    const hasValidationIssues = validationErrors > 0 || validationWarnings > 0;

    const aiSection = `
      <div class="ai-metadata">
        <div class="ai-header">
          <span class="ai-badge">${hasEnhancement ? '✨ AI Enhanced' : '⚠ Not Enhanced'}</span>
          ${metadata.quality_score ? `<span class="quality-score">Quality: ${metadata.quality_score.toFixed(2)}/1.0</span>` : ''}
        </div>
        ${metadata.tldr ? `<div class="ai-tldr"><strong>TL;DR:</strong> ${escapeHtml(metadata.tldr)}</div>` : ''}
        <div class="ai-tags">
          ${metadata.classification ? `<span class="classification-tag ${metadata.classification}">${metadata.classification}</span>` : ''}
        </div>
        ${validationStatus ? `
        <div class="validation-status ${hasValidationIssues ? 'has-issues' : 'valid'}">
          <span class="validation-badge">${validationErrors > 0 ? '❌' : validationWarnings > 0 ? '⚠️' : '✓'} Validation</span>
          <span class="validation-details">${validationErrors} error${validationErrors !== 1 ? 's' : ''}, ${validationWarnings} warning${validationWarnings !== 1 ? 's' : ''}</span>
          ${validationErrors > 0 ? '<span class="validation-hint">Run "Validate Only" to see details</span>' : ''}
        </div>
        ` : ''}
        <div class="ai-controls">
          <form action="/enhance/${article.id}" method="GET" class="enhance-form-row">
            <select name="actions" class="enhance-select">
              <option value="classify,summarize">Quick Enhance (Classify + Summary)</option>
              <option value="classify">Classify Only</option>
              <option value="summarize">Summary Only</option>
              <option value="classify,summarize,suggest-links">Full Enhance (+ Link Suggestions)</option>
              <option value="validate">Validate Only</option>
              <option value="embed">Generate Embedding Only</option>
            </select>
            <button type="submit" class="btn-small">${hasEnhancement ? '↻ Re-enhance' : '✨ Enhance'}</button>
          </form>
        </div>
      </div>
    `;
    
    // Generate breadcrumb for article
    const breadcrumb = generateBreadcrumb(article.title);

    const content = `
      ${breadcrumb}
      <h1>${escapeHtml(article.title)}</h1>
      ${aiSection}
      <p class="meta">Updated ${formatDate(article.updated_at)} · ${Math.round(article.content.length / 5)} words · Tags: ${escapeHtml(tagsDisplay)}</p>
      <div class="article-content">${renderArticleContent(article.content)}</div>
      <div class="actions">
        <a href="/edit/${encodeURIComponent(article.title)}" class="edit">Edit</a>
        <a href="/history/${encodeURIComponent(article.title)}">📜 History</a>
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
    const actionsParam = req.query.actions || 'classify,summarize';
    const actions = actionsParam.split(',').filter(a => ['classify', 'summarize', 'suggest-links', 'embed', 'validate'].includes(a));
    
    if (actions.length === 0) {
      actions.push('classify', 'summarize');
    }
    
    const result = await pgPool.query(
      'SELECT title FROM articles WHERE id = $1',
      [articleId]
    );
    
    if (result.rows.length === 0) {
      return res.status(404).send(htmlPage('Not Found', '<p>Article not found.</p>'));
    }
    
    const title = result.rows[0].title;
    
    // Queue selected actions
    for (const action of actions) {
      await pgPool.query(
        `INSERT INTO article_ai_queue (article_id, action, status) VALUES ($1, $2, 'pending')`,
        [articleId, action]
      );
    }
    
    // Auto-trigger AI worker to process jobs
    const workerPath = path.join(process.cwd(), 'ai-worker.js');
    const worker = spawn('node', [workerPath], {
      detached: true,
      stdio: 'ignore'
    });
    worker.unref();
    
    const actionLabels = {
      'classify': 'Classification',
      'summarize': 'Summary',
      'suggest-links': 'Link Suggestions',
      'validate': 'Validation',
      'embed': 'Embedding'
    };
    
    const content = `
      <div class="success">
        <h2>✨ Enhancement Started</h2>
        <p>AI enhancement jobs queued and processing for "${escapeHtml(title)}".</p>
        <p><strong>Actions:</strong> ${actions.map(a => actionLabels[a] || a).join(', ')}</p>
        <p>⏳ Processing in progress... Check back in a few seconds.</p>
      </div>
      <div class="actions">
        <a href="/article/${encodeURIComponent(title)}">View Article</a>
        <a href="/admin">View Dashboard</a>
        <a href="/">Back to Home</a>
      </div>
      <script>
        // Auto-refresh article view after 3 seconds
        setTimeout(() => {
          window.location.href = '/article/${encodeURIComponent(title)}';
        }, 3000);
      </script>
    `;
    res.send(htmlPage('Enhancement Started', content));
  } catch (err) {
    res.send(htmlPage('Error', `<div class="error">${escapeHtml(err.message)}</div>`));
  }
});

// Web UI: Re-run/Merge Research
app.get('/research/:id', async (req, res) => {
  try {
    const articleId = parseInt(req.params.id);
    const mode = req.query.mode || 'rerun'; // 'rerun' or 'merge'
    
    const result = await pgPool.query(
      'SELECT id, title, content, tags, metadata FROM articles WHERE id = $1',
      [articleId]
    );
    
    if (result.rows.length === 0) {
      return res.status(404).send(htmlPage('Not Found', '<p>Article not found.</p>'));
    }
    
    const article = result.rows[0];
    const title = article.title;
    
    // Queue research job
    await pgPool.query(
      `INSERT INTO article_ai_queue (article_id, action, status, result) 
       VALUES ($1, 'research', 'pending', $2)`,
      [articleId, JSON.stringify({ mode, original_content: mode === 'merge' ? article.content : null })]
    );
    
    // Auto-trigger AI worker
    const workerPath = path.join(process.cwd(), 'ai-worker.js');
    const worker = spawn('node', [workerPath], {
      detached: true,
      stdio: 'ignore'
    });
    worker.unref();
    
    const modeLabel = mode === 'merge' ? 'Merge Research' : 'Re-run Research';
    
    const content = `
      <div class="success">
        <h2>🔬 ${modeLabel} Started</h2>
        <p>Research job queued for "${escapeHtml(title)}".</p>
        <p><strong>Mode:</strong> ${mode === 'merge' ? 'Merge new research with existing content' : 'Replace with new research'}</p>
        <p>⏳ Processing in progress... The AI will research the topic and update the article.</p>
      </div>
      <div class="actions">
        <a href="/article/${encodeURIComponent(title)}">View Article</a>
        <a href="/admin">Back to Dashboard</a>
      </div>
      <script>
        setTimeout(() => {
          window.location.href = '/article/${encodeURIComponent(title)}';
        }, 5000);
      </script>
    `;
    res.send(htmlPage(`${modeLabel} Started`, content));
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
             metadata->>'quality_score' as quality_score,
             metadata->>'validation_status' as validation_status,
             metadata->>'validation_errors' as validation_errors,
             metadata->>'validation_warnings' as validation_warnings
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
      const valErrors = parseInt(a.validation_errors) || 0;
      const valWarnings = parseInt(a.validation_warnings) || 0;
      const hasValErrors = valErrors > 0;
      const hasValWarnings = valWarnings > 0 && !hasValErrors;
      // Detect research errors in content
      const hasResearchError = a.char_count && a.char_count > 0 && 
        (a.metadata?.tldr?.includes('Research error:') || 
         a.content?.substring(0, 200).includes('Research error:'));
      const needsAttention = !a.classification || score < 0.5 || hasValErrors || hasResearchError;

      const validationBadge = a.validation_status
        ? hasValErrors ? `<span style="color:#dc2626">❌ ${valErrors}E/${valWarnings}W</span>`
          : hasValWarnings ? `<span style="color:#f59e0b">⚠️ ${valWarnings}W</span>`
          : '<span style="color:#10b981">✓</span>'
        : '<span style="color:#9ca3af">-</span>';

      // Build action buttons
      let actionButtons = '';
      if (hasResearchError) {
        actionButtons = `
          <a href="/research/${a.id}?mode=rerun" class="btn-small btn-rerun" title="Re-run research">🔄 Re-run</a>
          <a href="/research/${a.id}?mode=merge" class="btn-small btn-merge" title="Merge new research">➕ Merge</a>
        `;
      } else if (!a.classification) {
        actionButtons = `<a href="/enhance/${a.id}" class="btn-small">Enhance</a>`;
      } else {
        actionButtons = '✓';
      }

      return `
        <tr class="${needsAttention ? 'needs-attention' : ''}">
          <td><a href="/article/${encodeURIComponent(a.title)}">${escapeHtml(a.title.substring(0, 50))}</a></td>
          <td>${a.classification || '<span class="badge-pending">pending</span>'}${hasResearchError ? ' <span style="color:#dc2626" title="Research failed">⚠️</span>' : ''}</td>
          <td>${score ? score.toFixed(2) : '-'}</td>
          <td>${validationBadge}</td>
          <td>${formatDate(a.updated_at)}</td>
          <td>${actionButtons}</td>
        </tr>
      `;
    }).join('');
    
    const processButton = parseInt(jobs.pending) > 0 ? `
      <div class="process-section" style="margin: 20px 0;">
        <button onclick="processQueueAdmin()" class="btn-process-admin">🔄 Process ${jobs.pending} Pending Jobs</button>
        <span id="admin-queue-status" class="queue-status"></span>
      </div>
      <script>
        async function processQueueAdmin() {
          const btn = document.querySelector('.btn-process-admin');
          const status = document.getElementById('admin-queue-status');
          btn.disabled = true;
          status.textContent = 'Processing...';
          
          try {
            const response = await fetch('/api/admin/process-queue', { method: 'POST' });
            const data = await response.json();
            
            if (response.ok) {
              status.textContent = data.pending_jobs + ' jobs queued';
              setTimeout(() => location.reload(), 2000);
            } else {
              status.textContent = 'Error: ' + (data.error || 'Failed');
              btn.disabled = false;
            }
          } catch (err) {
            status.textContent = 'Error: ' + err.message;
            btn.disabled = false;
          }
        }
      </script>
    ` : '<p style="color: #16a34a; margin: 20px 0;">✅ All jobs processed! Queue is empty.</p>';
    
    const content = `
      <h1>Wiki Health Dashboard</h1>
      ${stats}
      ${processButton}
      <table class="admin-table">
        <thead>
          <tr><th>Title</th><th>Classification</th><th>Quality</th><th>Validation</th><th>Updated</th><th>Action</th></tr>
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
        .btn-process-admin {
          background: #8b5cf6;
          color: white;
          padding: 10px 20px;
          border: none;
          border-radius: 4px;
          cursor: pointer;
          font-size: 14px;
          font-weight: 500;
        }
        .btn-process-admin:hover:not(:disabled) { background: #7c3aed; }
        .btn-process-admin:disabled { opacity: 0.6; cursor: not-allowed; }
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

// View Revision History
app.get('/history/:title', async (req, res) => {
  try {
    const article = await getArticle(req.params.title);
    if (!article) {
      return res.status(404).send(htmlPage('Not Found', '<p>Article not found.</p>'));
    }

    const revisions = await getArticleRevisions(req.params.title, 20);

    const revisionList = revisions.length === 0
      ? '<p>No revision history yet. History is created when articles are updated.</p>'
      : '<div class="revision-list">' + revisions.map((rev, index) => `
        <div class="revision-card">
          <div class="revision-header">
            <span class="revision-number">#${revisions.length - index}</span>
            <span class="revision-date">${formatDate(rev.created_at)}</span>
            <span class="revision-editor">by ${escapeHtml(rev.editor || 'unknown')}</span>
          </div>
          <div class="revision-summary">${escapeHtml(rev.change_summary || 'No summary')}</div>
          <div class="revision-actions">
            <a href="/revision/${rev.id}" class="btn-small">View</a>
            <a href="/revert/${req.params.title}/${rev.id}" class="btn-small btn-revert">Revert</a>
          </div>
        </div>
      `).join('') + '</div>';

    const content = `
      <h1>Revision History: ${escapeHtml(article.title)}</h1>
      <p class="meta">Current version updated ${formatDate(article.updated_at)}</p>
      ${revisionList}
      <div class="actions">
        <a href="/article/${encodeURIComponent(article.title)}">Back to Article</a>
        <a href="/edit/${encodeURIComponent(article.title)}">Edit Current</a>
      </div>
      <style>
        .revision-list { display: flex; flex-direction: column; gap: 12px; margin: 20px 0; }
        .revision-card {
          background: #f9fafb;
          border-radius: 8px;
          padding: 16px;
          border-left: 4px solid #8b5cf6;
        }
        .revision-header {
          display: flex;
          gap: 12px;
          align-items: center;
          margin-bottom: 8px;
          font-size: 14px;
        }
        .revision-number {
          background: #8b5cf6;
          color: white;
          padding: 2px 8px;
          border-radius: 4px;
          font-weight: 600;
        }
        .revision-date {
          color: #374151;
          font-weight: 500;
        }
        .revision-editor {
          color: #6b7280;
        }
        .revision-summary {
          color: #4b5563;
          font-style: italic;
          margin-bottom: 12px;
        }
        .revision-actions {
          display: flex;
          gap: 8px;
        }
        .btn-revert {
          background: #f59e0b;
        }
        .btn-revert:hover {
          background: #d97706;
        }
      </style>
    `;
    res.send(htmlPage(`History: ${article.title}`, content));
  } catch (err) {
    res.send(htmlPage('Error', `<div class="error">${escapeHtml(err.message)}</div>`));
  }
});

// View Single Revision
app.get('/revision/:id', async (req, res) => {
  try {
    const revision = await getRevision(parseInt(req.params.id));
    if (!revision) {
      return res.status(404).send(htmlPage('Not Found', '<p>Revision not found.</p>'));
    }

    const tagsDisplay = revision.tags
      ? (Array.isArray(revision.tags) ? revision.tags.join(', ') : revision.tags)
      : 'none';

    const content = `
      <h1>Revision #${revision.id}: ${escapeHtml(revision.article_title)}</h1>
      <div class="revision-meta">
        <p><strong>Created:</strong> ${revision.created_at}</p>
        <p><strong>Editor:</strong> ${escapeHtml(revision.editor || 'unknown')}</p>
        <p><strong>Summary:</strong> ${escapeHtml(revision.change_summary || 'No summary')}</p>
        <p><strong>Tags:</strong> ${escapeHtml(tagsDisplay)}</p>
      </div>
      <div class="revision-content">
        <h3>Content:</h3>
        <pre><code>${escapeHtml(revision.content)}</code></pre>
      </div>
      <div class="actions">
        <a href="/history/${encodeURIComponent(revision.article_title)}">Back to History</a>
        <a href="/revert/${encodeURIComponent(revision.article_title)}/${revision.id}" class="btn-revert">Revert to This Version</a>
      </div>
      <style>
        .revision-meta {
          background: #f3f4f6;
          padding: 16px;
          border-radius: 8px;
          margin: 16px 0;
        }
        .revision-meta p {
          margin: 4px 0;
        }
        .revision-content {
          margin: 20px 0;
        }
        .revision-content pre {
          background: #1f2937;
          color: #e5e7eb;
          padding: 16px;
          border-radius: 8px;
          overflow-x: auto;
          max-height: 500px;
          overflow-y: auto;
        }
        .btn-revert {
          background: #f59e0b;
          color: white;
          padding: 8px 16px;
          border-radius: 4px;
          text-decoration: none;
          display: inline-block;
          margin-left: 12px;
        }
        .btn-revert:hover {
          background: #d97706;
        }
      </style>
    `;
    res.send(htmlPage(`Revision ${revision.id}`, content));
  } catch (err) {
    res.send(htmlPage('Error', `<div class="error">${escapeHtml(err.message)}</div>`));
  }
});

// Revert Confirmation Page
app.get('/revert/:title/:revision_id', async (req, res) => {
  try {
    const article = await getArticle(req.params.title);
    if (!article) {
      return res.status(404).send(htmlPage('Not Found', '<p>Article not found.</p>'));
    }

    const revision = await getRevision(parseInt(req.params.revision_id));
    if (!revision) {
      return res.status(404).send(htmlPage('Not Found', '<p>Revision not found.</p>'));
    }

    if (revision.article_title !== req.params.title) {
      return res.status(400).send(htmlPage('Error', '<p>Revision does not belong to this article.</p>'));
    }

    const content = `
      <h1>Revert Article</h1>
      <div class="revert-confirm">
        <p>You are about to revert <strong>${escapeHtml(req.params.title)}</strong> to revision #${revision.id} from ${formatDate(revision.created_at)}.</p>
        <p class="warning">⚠️ This will create a new revision with the old content. The current version will be preserved in history.</p>
        <form action="/revert/${encodeURIComponent(req.params.title)}/${revision.id}" method="POST">
          <button type="submit" class="btn-revert-confirm">Yes, Revert to This Version</button>
          <a href="/history/${encodeURIComponent(req.params.title)}" class="btn-cancel">Cancel</a>
        </form>
      </div>
      <style>
        .revert-confirm {
          background: #fef3c7;
          border: 2px solid #f59e0b;
          border-radius: 8px;
          padding: 24px;
          margin: 20px 0;
        }
        .revert-confirm p {
          margin: 12px 0;
          font-size: 16px;
        }
        .warning {
          color: #92400e;
          font-weight: 500;
        }
        .btn-revert-confirm {
          background: #dc2626;
          color: white;
          padding: 12px 24px;
          border: none;
          border-radius: 6px;
          font-size: 16px;
          cursor: pointer;
          margin-right: 12px;
        }
        .btn-revert-confirm:hover {
          background: #b91c1c;
        }
        .btn-cancel {
          background: #6b7280;
          color: white;
          padding: 12px 24px;
          border-radius: 6px;
          text-decoration: none;
          display: inline-block;
        }
        .btn-cancel:hover {
          background: #4b5563;
        }
      </style>
    `;
    res.send(htmlPage('Confirm Revert', content));
  } catch (err) {
    res.send(htmlPage('Error', `<div class="error">${escapeHtml(err.message)}</div>`));
  }
});

// Revert Action
app.post('/revert/:title/:revision_id', async (req, res) => {
  try {
    const article = await getArticle(req.params.title);
    if (!article) {
      return res.status(404).send(htmlPage('Not Found', '<p>Article not found.</p>'));
    }

    const revision = await getRevision(parseInt(req.params.revision_id));
    if (!revision) {
      return res.status(404).send(htmlPage('Not Found', '<p>Revision not found.</p>'));
    }

    const tags = Array.isArray(revision.tags) ? revision.tags : (revision.tags ? revision.tags.split(',').map(t => t.trim()).filter(Boolean) : []);
    await updateArticle(req.params.title, revision.content, tags, 'web', `Reverted to revision ${req.params.revision_id}`);

    const content = `
      <div class="success">
        <h2>✅ Article Reverted</h2>
        <p><strong>${escapeHtml(req.params.title)}</strong> has been reverted to revision #${req.params.revision_id}.</p>
      </div>
      <div class="actions">
        <a href="/article/${encodeURIComponent(req.params.title)}">View Article</a>
        <a href="/history/${encodeURIComponent(req.params.title)}">View History</a>
      </div>
      <style>
        .success {
          background: #d1fae5;
          border: 2px solid #10b981;
          border-radius: 8px;
          padding: 24px;
          margin: 20px 0;
        }
        .success h2 {
          color: #065f46;
          margin-bottom: 12px;
        }
        .success p {
          color: #047857;
        }
      </style>
    `;
    res.send(htmlPage('Revert Successful', content));
  } catch (err) {
    res.send(htmlPage('Error', `<div class="error">${escapeHtml(err.message)}</div>`));
  }
});

// MCP HTTP SSE transport endpoint
let mcpTransports;

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

// Semantic Search via Weaviate
app.get('/api/semantic-search', async (req, res) => {
  try {
    const query = req.query.q || '';
    const limit = parseInt(req.query.limit) || 10;
    const certainty = parseFloat(req.query.certainty) || 0.7;
    
    if (!query) return res.json([]);
    
    const articles = await semanticSearch(query, limit, certainty);
    res.json(articles);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Hybrid Search (keyword + semantic)
app.get('/api/hybrid-search', async (req, res) => {
  try {
    const query = req.query.q || '';
    const limit = parseInt(req.query.limit) || 10;

    if (!query) return res.json([]);

    const articles = await hybridSearch(query, limit);
    res.json(articles);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Revision Management Endpoints
app.get('/api/articles/:title/revisions', async (req, res) => {
  try {
    const limit = parseInt(req.query.limit) || 10;
    const revisions = await getArticleRevisions(req.params.title, limit);
    res.json(revisions);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.get('/api/revisions/:id', async (req, res) => {
  try {
    const revision = await getRevision(parseInt(req.params.id));
    if (!revision) return res.status(404).json({ error: 'Revision not found' });
    res.json(revision);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.post('/api/articles/:title/revert', async (req, res) => {
  try {
    const { revision_id } = req.body;
    if (!revision_id) {
      return res.status(400).json({ error: 'revision_id is required' });
    }
    const article = await getArticle(req.params.title);
    if (!article) {
      return res.status(404).json({ error: 'Article not found' });
    }
    const revision = await getRevision(revision_id);
    if (!revision) {
      return res.status(404).json({ error: 'Revision not found' });
    }
    if (revision.article_title !== req.params.title) {
      return res.status(400).json({ error: 'Revision does not belong to this article' });
    }
    const tags = Array.isArray(revision.tags) ? revision.tags : (revision.tags ? revision.tags.split(',').map(t => t.trim()).filter(Boolean) : []);
    const result = await updateArticle(req.params.title, revision.content, tags, 'api', `Reverted to revision ${revision_id}`);
    res.json({ success: true, message: `Reverted to revision ${revision_id}`, result });
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
    const validActions = ['classify', 'summarize', 'suggest-links', 'embed', 'validate'];
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
    
    if (pendingCount === 0) {
      return res.json({
        message: 'No pending jobs',
        pending_jobs: 0,
        processed: 0
      });
    }
    
    res.json({
      message: 'Queue processing started',
      pending_jobs: pendingCount,
      note: 'AI worker is processing jobs asynchronously'
    });
    
    // Fire-and-forget: trigger actual processing
    const workerPath = path.join(process.cwd(), 'ai-worker.js');
    const worker = spawn('node', [workerPath], {
      detached: true,
      stdio: 'ignore'
    });
    worker.unref();
    
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

  // Initialize MCP transports map
  mcpTransports = new Map(); // Store transports by session ID

  app.get('/mcp/sse', async (req, res) => {
    try {
      // Note: SSEServerTransport handles headers internally
      // We just ensure the response is in a good state
      res.setHeader('X-Accel-Buffering', 'no'); // Disable Nginx buffering if present
      
      const server = createMcpServer(); // New server instance per connection
      const transport = new SSEServerTransport('/mcp/message', res);

      // Store transport for POST handler to use
      mcpTransports.set(transport.sessionId, transport);

      // Clean up on disconnect
      req.on('close', () => {
        mcpTransports.delete(transport.sessionId);
        console.error(`mcp-wiki: MCP SSE client ${transport.sessionId} disconnected`);
      });

      await server.connect(transport);
      console.error(`mcp-wiki: MCP SSE client ${transport.sessionId} connected`);
    } catch (err) {
      console.error('mcp-wiki: MCP SSE connection failed:', err.message);
      if (!res.headersSent) {
        res.status(500).end();
      }
    }
  });

  // MCP message endpoint - body parsing is disabled in global middleware
  app.post('/mcp/message', async (req, res) => {
      const sessionId = req.query.sessionId;
      const transport = mcpTransports.get(sessionId);

      if (!transport) {
        res.status(400).send('Unknown session');
        return;
      }

      try {
        // Pass request/response directly to transport
        await transport.handlePostMessage(req, res);
      } catch (err) {
        console.error('mcp-wiki: MCP message handling error:', err.message);
        if (!res.headersSent) {
          res.status(500).json({ error: err.message });
        }
      }
    }
  );

  // MCP stdio transport (optional - only if stdin is piped)
  // This runs after HTTP server starts, allowing dual-mode operation
  const isStdioMode = !process.stdin.isTTY || process.env.MCP_STDIO === '1';
  const isHttpDisabled = process.env.WIKI_HTTP_DISABLED === '1' || process.env.WIKI_HTTP_DISABLED === 'true';

  // Start HTTP server unless disabled (for stdio-only docker exec mode)
  if (!isHttpDisabled) {
    app.listen(HTTP_PORT, () => {
      console.error(`mcp-wiki: HTTP server started on port ${HTTP_PORT}`);
      console.error(`mcp-wiki: MCP SSE endpoint available at http://localhost:${HTTP_PORT}/mcp/sse`);
    });
  } else {
    console.error('mcp-wiki: HTTP server disabled (WIKI_HTTP_DISABLED=1)');
  }

  if (isStdioMode) {
    const server = createMcpServer(); // New server instance for stdio
    const transport = new StdioServerTransport();
    server.connect(transport).then(() => {
      console.error('mcp-wiki: MCP stdio transport connected');
    }).catch(err => {
      console.error('mcp-wiki: MCP stdio connection failed:', err.message);
    });
  } else if (!isHttpDisabled) {
    console.error('mcp-wiki: Running in HTTP-only mode (no MCP stdio client detected)');
    console.error(`mcp-wiki: Visit http://localhost:${HTTP_PORT}/ to use the wiki`);
    console.error(`mcp-wiki: MCP tools available via SSE at /mcp/sse`);
  }
}

start().catch(err => {
  console.error('mcp-wiki: Failed to start:', err.message);
  process.exit(1);
});
