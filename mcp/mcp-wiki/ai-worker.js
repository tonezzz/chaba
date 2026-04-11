#!/usr/bin/env node
/**
 * Wiki AI Worker - Processes article enhancement jobs
 * 
 * Usage:
 *   node ai-worker.js                    # Process all pending jobs once
 *   node ai-worker.js --daemon           # Run continuously
 *   node ai-worker.js --article-id 123   # Process specific article
 */

import pg from 'pg';

const { Pool } = pg;

const DATABASE_URL = process.env.DATABASE_URL || 'postgresql://chaba:changeme@idc1.surf-thailand.com:5432/chaba';
const OPENROUTER_API_KEY = process.env.OPENROUTER_API_KEY || '';

const pool = new Pool({ connectionString: DATABASE_URL });

// Simple classification based on content analysis
async function classifyArticle(content) {
  const lower = content.toLowerCase();
  
  // Heuristic classification
  if (lower.includes('error') || lower.includes('fix') || lower.includes('troubleshoot')) {
    return { type: 'troubleshooting', complexity: 'intermediate' };
  }
  if (lower.includes('how to') || lower.includes('guide') || lower.includes('step')) {
    return { type: 'tutorial', complexity: lower.includes('advanced') ? 'advanced' : 'basic' };
  }
  if (lower.includes('reference') || lower.includes('api') || lower.includes('endpoint')) {
    return { type: 'reference', complexity: 'intermediate' };
  }
  if (lower.includes('architecture') || lower.includes('design') || lower.includes('pattern')) {
    return { type: 'architecture', complexity: 'advanced' };
  }
  
  return { type: 'documentation', complexity: 'intermediate' };
}

// Extract tags from content
async function extractTags(content, title) {
  const tags = new Set();
  const lower = content.toLowerCase();
  
  // Common tech tags
  const techTerms = {
    'docker': 'docker', 'kubernetes': 'kubernetes', 'k8s': 'kubernetes',
    'postgres': 'postgresql', 'postgresql': 'postgresql', 'redis': 'redis',
    'api': 'api', 'http': 'http', 'rest': 'rest-api', 'graphql': 'graphql',
    'python': 'python', 'javascript': 'javascript', 'node': 'nodejs',
    'git': 'git', 'github': 'github', 'ci/cd': 'cicd', 'deployment': 'deployment',
    'security': 'security', 'auth': 'authentication', 'oauth': 'oauth',
    'database': 'database', 'cache': 'cache', 'queue': 'queue',
    'microservice': 'microservices', 'service': 'services',
    'monitoring': 'monitoring', 'logging': 'logging', 'metrics': 'metrics',
    'idc1': 'idc1', 'chaba': 'chaba', 'autoagent': 'autoagent',
    'mcp': 'mcp', 'wiki': 'wiki', 'portainer': 'portainer'
  };
  
  for (const [term, tag] of Object.entries(techTerms)) {
    if (lower.includes(term)) {
      tags.add(tag);
    }
  }
  
  // Add title-based tags
  const titleLower = title.toLowerCase();
  if (titleLower.includes('guide') || titleLower.includes('how')) tags.add('guide');
  if (titleLower.includes('config') || titleLower.includes('setup')) tags.add('configuration');
  if (titleLower.includes('deploy')) tags.add('deployment');
  if (titleLower.includes('troubleshoot') || titleLower.includes('debug')) tags.add('troubleshooting');
  if (titleLower.includes('reference')) tags.add('reference');
  if (titleLower.includes('api')) tags.add('api');
  
  return Array.from(tags).slice(0, 7); // Max 7 tags
}

// Generate TL;DR summary
async function generateSummary(content) {
  // Simple summary: first 2-3 sentences or first 200 chars
  const sentences = content.match(/[^.!?]+[.!?]+/g) || [];
  let summary = sentences.slice(0, 2).join(' ').trim();
  
  if (summary.length > 250) {
    summary = summary.substring(0, 250) + '...';
  }
  
  return summary || content.substring(0, 200) + '...';
}

// Calculate quality score
function calculateQualityScore(content, tags) {
  let score = 0.5;
  
  // Length score
  const wordCount = content.split(/\s+/).length;
  if (wordCount > 100) score += 0.1;
  if (wordCount > 300) score += 0.1;
  if (wordCount > 500) score += 0.1;
  
  // Structure score
  if (content.includes('```')) score += 0.1; // Has code blocks
  if (content.includes('#')) score += 0.05; // Has headers
  if (content.includes('|')) score += 0.05; // Has tables
  if (content.includes('http')) score += 0.05; // Has links
  
  // Tags bonus
  if (tags && tags.length > 0) score += Math.min(tags.length * 0.02, 0.1);
  
  return Math.min(Math.round(score * 100) / 100, 1.0);
}

// Process a single job
async function processJob(job) {
  console.log(`Processing job ${job.id}: ${job.action} for article ${job.article_id}`);
  
  try {
    // Get article content
    const articleResult = await pool.query(
      'SELECT id, title, content, tags FROM articles WHERE id = $1',
      [job.article_id]
    );
    
    if (articleResult.rows.length === 0) {
      throw new Error('Article not found');
    }
    
    const article = articleResult.rows[0];
    let result = {};
    let metadataUpdate = {};
    
    switch (job.action) {
      case 'classify':
        const classification = await classifyArticle(article.content);
        const suggestedTags = await extractTags(article.content, article.title);
        const qualityScore = calculateQualityScore(article.content, article.tags);
        
        result = { classification, suggestedTags, qualityScore };
        metadataUpdate = {
          classification: classification.type,
          complexity: classification.complexity,
          suggested_tags: suggestedTags,
          quality_score: qualityScore,
          word_count: article.content.split(/\s+/).length
        };
        break;
        
      case 'summarize':
        const tldr = await generateSummary(article.content);
        result = { tldr };
        metadataUpdate = { tldr };
        break;
        
      case 'suggest-links':
        // Find other articles that might be related
        const allArticles = await pool.query(
          'SELECT id, title FROM articles WHERE id != $1 LIMIT 20',
          [job.article_id]
        );
        
        const contentLower = article.content.toLowerCase();
        const relatedArticles = allArticles.rows
          .filter(a => contentLower.includes(a.title.toLowerCase()) || 
                      a.title.toLowerCase().includes(article.title.toLowerCase().split(' ')[0]))
          .slice(0, 5);
        
        result = { relatedArticles: relatedArticles.map(a => a.title) };
        metadataUpdate = { related_articles: relatedArticles.map(a => ({ title: a.title, id: a.id })) };
        break;
        
      default:
        throw new Error(`Unknown action: ${job.action}`);
    }
    
    // Update article metadata
    await pool.query(
      `UPDATE articles 
       SET metadata = COALESCE(metadata, '{}') || $1::jsonb,
           updated_at = NOW()
       WHERE id = $2`,
      [JSON.stringify(metadataUpdate), job.article_id]
    );
    
    // Mark job as completed
    await pool.query(
      `UPDATE article_ai_queue 
       SET status = 'done', result = $1, processed_at = NOW()
       WHERE id = $2`,
      [JSON.stringify(result), job.id]
    );
    
    console.log(`  ✓ Completed: ${job.action}`);
    return result;
    
  } catch (err) {
    console.error(`  ✗ Failed: ${err.message}`);
    await pool.query(
      `UPDATE article_ai_queue 
       SET status = 'error', error = $1, processed_at = NOW()
       WHERE id = $2`,
      [err.message, job.id]
    );
    throw err;
  }
}

// Main processing loop
async function processPendingJobs(limit = 10) {
  const result = await pool.query(
    `SELECT id, article_id, action, status, created_at 
     FROM article_ai_queue 
     WHERE status = 'pending'
     ORDER BY created_at ASC
     LIMIT $1`,
    [limit]
  );
  
  console.log(`Found ${result.rows.length} pending jobs`);
  
  for (const job of result.rows) {
    try {
      await processJob(job);
    } catch (err) {
      console.error(`Job ${job.id} failed:`, err.message);
    }
  }
  
  return result.rows.length;
}

// Process specific article
async function processArticle(articleId, actions = ['classify', 'summarize']) {
  console.log(`Processing article ${articleId} with actions: ${actions.join(', ')}`);
  
  // Queue jobs
  const jobs = [];
  for (const action of actions) {
    const result = await pool.query(
      `INSERT INTO article_ai_queue (article_id, action, status) 
       VALUES ($1, $2, 'pending') 
       RETURNING id, action, status`,
      [articleId, action]
    );
    jobs.push(result.rows[0]);
  }
  
  console.log(`Queued ${jobs.length} jobs`);
  
  // Process immediately
  for (const job of jobs) {
    await processJob({ ...job, article_id: articleId });
  }
  
  return jobs;
}

// Main
async function main() {
  const args = process.argv.slice(2);
  const isDaemon = args.includes('--daemon');
  const articleId = args.includes('--article-id') ? 
    parseInt(args[args.indexOf('--article-id') + 1]) : null;
  
  console.log('Wiki AI Worker Started');
  console.log(`Mode: ${articleId ? 'Single Article' : isDaemon ? 'Daemon' : 'One-time'}`);
  console.log('');
  
  try {
    if (articleId) {
      await processArticle(articleId);
    } else if (isDaemon) {
      console.log('Running in daemon mode (Ctrl+C to stop)');
      while (true) {
        const processed = await processPendingJobs(5);
        if (processed === 0) {
          console.log('No pending jobs, waiting 30s...');
          await new Promise(r => setTimeout(r, 30000));
        }
      }
    } else {
      const processed = await processPendingJobs(10);
      console.log(`\nProcessed ${processed} jobs`);
    }
  } catch (err) {
    console.error('Worker error:', err);
    process.exit(1);
  } finally {
    await pool.end();
  }
}

main();
