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

// Common tech terms for spell checking
const TECH_TERMS = new Set([
  'api', 'http', 'https', 'json', 'xml', 'yaml', 'url', 'uri',
  'docker', 'kubernetes', 'k8s', 'container', 'pod', 'deployment',
  'postgres', 'postgresql', 'mysql', 'mongodb', 'redis', 'sqlite',
  'python', 'javascript', 'typescript', 'nodejs', 'react', 'vue',
  'github', 'gitlab', 'git', 'ci/cd', 'cicd', 'pipeline',
  'auth', 'oauth', 'jwt', 'ssl', 'tls', 'encryption',
  'microservice', 'serverless', 'lambda', 'function',
  'websocket', 'grpc', 'graphql', 'rest',
  'mermaid', 'flowchart', 'sequenceDiagram', 'classDiagram',
  'idc1', 'chaba', 'autoagent', 'jarvis', 'portainer'
]);

// Common spelling mistakes to catch
const COMMON_MISSPELLINGS = {
  'recieve': 'receive', 'seperate': 'separate', 'occured': 'occurred',
  'definately': 'definitely', 'occurence': 'occurrence', 'independant': 'independent',
  'enviroment': 'environment', 'accomodate': 'accommodate', 'commited': 'committed',
  'neccessary': 'necessary', 'sucessful': 'successful', 'responsability': 'responsibility',
  'maintainance': 'maintenance', 'potatos': 'potatoes', 'tomatos': 'tomatoes',
  'begining': 'beginning', 'beleive': 'believe', 'calender': 'calendar',
  'catagory': 'category', 'collegue': 'colleague', 'concious': 'conscious',
  'curiousity': 'curiosity', 'embarass': 'embarrass', 'existance': 'existence',
  'foriegn': 'foreign', 'goverment': 'government', 'harrass': 'harass',
  'imediately': 'immediately', 'individaul': 'individual', 'knowlege': 'knowledge',
  'liason': 'liaison', 'millenium': 'millennium', 'neighbour': 'neighbor',
  'noticable': 'noticeable', 'ocassion': 'occasion', 'pasttime': 'pastime',
  'perseverance': 'perseverance', 'posession': 'possession', 'pronounciation': 'pronunciation',
  'publically': 'publicly', 'recomend': 'recommend', 'refering': 'referring',
  'religous': 'religious', 'repetion': 'repetition', 'restaraunt': 'restaurant',
  'rythm': 'rhythm', 'sieze': 'seize', 'supercede': 'supersede',
  'suprise': 'surprise', 'tommorow': 'tomorrow', 'untill': 'until',
  'weild': 'wield', 'wich': 'which', 'withing': 'within'
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
    errors: errors.slice(0, 10), // Limit to first 10
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

    // Check for flowchart/graph TD syntax errors
    if (firstLine.includes('flowchart') || firstLine.includes('graph ')) {
      // Check for unclosed arrows
      const arrowLines = lines.filter(l => l.includes('-->') || l.includes('==>'));
      arrowLines.forEach((line, lineNum) => {
        // Check for orphan arrows (no source or target)
        if (line.match(/^\s*-->/) || line.match(/-->\s*$/)) {
          errors.push({
            type: 'mermaid',
            severity: 'error',
            message: `Diagram #${index + 1}, line ${lineNum + 2}: Arrow without source or target`,
            line: line.substring(0, 50),
            fix: 'Format: A --> B or A -->|label| B'
          });
        }
      });

      // Check for unclosed brackets in node definitions
      const nodeLines = lines.filter(l => l.includes('[') || l.includes('(') || l.includes('{'));
      nodeLines.forEach((line, lineNum) => {
        const openSquare = (line.match(/\[/g) || []).length;
        const closeSquare = (line.match(/\]/g) || []).length;
        const openRound = (line.match(/\(/g) || []).length;
        const closeRound = (line.match(/\)/g) || []).length;
        const openCurly = (line.match(/\{/g) || []).length;
        const closeCurly = (line.match(/\}/g) || []).length;

        if (openSquare !== closeSquare || openRound !== closeRound || openCurly !== closeCurly) {
          errors.push({
            type: 'mermaid',
            severity: 'error',
            message: `Diagram #${index + 1}, line ${lineNum + 2}: Unclosed brackets`,
            line: line.substring(0, 50),
            fix: 'Ensure all [, ], (, ), {, } are matched'
          });
        }
      });
    }

    // Check for sequence diagram syntax errors
    if (firstLine.includes('sequencediagram')) {
      const participantLines = lines.filter(l => l.toLowerCase().includes('participant') || l.toLowerCase().includes('actor'));
      if (participantLines.length === 0 && lines.length > 1) {
        warnings.push({
          type: 'mermaid',
          severity: 'warning',
          message: `Diagram #${index + 1}: No participants defined`,
          fix: 'Add: participant Name or actor Name'
        });
      }

      // Check for arrows without participants
      const arrowPattern = /(\w+)\s*(->>|-->|==>|\-\-x|->x|->\+)\s*(\w+)/;
      lines.forEach((line, lineNum) => {
        if (line.includes('->') && !arrowPattern.test(line)) {
          warnings.push({
            type: 'mermaid',
            severity: 'warning',
            message: `Diagram #${index + 1}, line ${lineNum + 2}: Possible invalid arrow syntax`,
            line: line.substring(0, 50),
            fix: 'Format: A ->> B: message or A --> B'
          });
        }
      });
    }

    // Check for excessive diagram size (may cause rendering issues)
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
      // Check for common JS syntax errors
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

      // Check for common JS mistakes
      if (code.includes('console.log') && !code.includes('//')) {
        warnings.push({
          type: 'code',
          severity: 'warning',
          language: lang,
          message: `JS code block #${index + 1}: Contains console.log (consider removing for production code)`,
          fix: 'Remove console.log or add // comment explaining its purpose'
        });
      }
    }

    if (lang === 'python' || lang === 'py') {
      // Check for indentation issues (simplified)
      const lines = code.split('\n');
      const indentedLines = lines.filter(l => l.startsWith(' ') && l.trim());
      if (indentedLines.length > 0) {
        const indentSizes = indentedLines.map(l => l.match(/^[\s]*/)[0].length);
        const nonStandard = indentSizes.filter(s => s % 4 !== 0 && s % 2 !== 0);
        if (nonStandard.length > 0) {
          warnings.push({
            type: 'code',
            severity: 'warning',
            language: lang,
            message: `Python code block #${index + 1}: Non-standard indentation detected`,
            fix: 'Use 4 spaces for Python indentation'
          });
        }
      }

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

      if (code.includes('$ ') && code.split('\n').some(l => l.startsWith('$ '))) {
        warnings.push({
          type: 'code',
          severity: 'warning',
          language: lang,
          message: `Bash code block #${index + 1}: Copy-paste unfriendly $ prompt included`,
          fix: 'Remove $ prefix or use comments to indicate output'
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

    // Check for TODO/FIXME comments
    const todos = (code.match(/TODO|FIXME|XXX|HACK/gi) || []);
    if (todos.length > 0) {
      warnings.push({
        type: 'code',
        severity: 'warning',
        message: `Code block #${index + 1}: Contains ${todos.length} TODO/FIXME comment(s)`,
        fix: 'Resolve or document why these are acceptable'
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

  // Check for tech terms (warn if tech terms look misspelled)
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

  // Check for inconsistent casing of tech terms
  const contentLower = content.toLowerCase();
  for (const term of TECH_TERMS) {
    const properCasing = term === 'api' || term === 'http' || term === 'url' ? term.toUpperCase() :
                        term === 'json' || term === 'xml' || term === 'yaml' ? term.toUpperCase() :
                        term.charAt(0).toUpperCase() + term.slice(1);

    // Skip if term is in all lowercase (acceptable)
    // Flag inconsistent casing like PostgreSQL vs postgresql vs Postgresql
    if (term.length > 4 && term !== properCasing.toLowerCase()) {
      const mixedCasePattern = new RegExp(`\\b${term.charAt(0).toUpperCase() + term.slice(1).toLowerCase()}\\b`, 'g');
      const mixedMatches = content.match(mixedCasePattern);
      if (mixedMatches && term !== properCasing) {
        // Just informational, not an error
      }
    }
  }

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
  if (content.includes('```')) score += 0.05; // Code blocks
  if (content.includes('|')) score += 0.03;   // Tables
  if (content.includes('> ')) score += 0.02;  // Blockquotes

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
    // Critical errors (-0.15 each, max -0.45)
    const criticalErrors = validationResult.errors.filter(e => e.severity === 'critical').length;
    score -= Math.min(criticalErrors * 0.15, 0.45);

    // Regular errors (-0.08 each, max -0.24)
    const regularErrors = validationResult.errors.filter(e => e.severity === 'error').length;
    score -= Math.min(regularErrors * 0.08, 0.24);

    // Warnings (-0.03 each, max -0.15)
    score -= Math.min(validationResult.warning_count * 0.03, 0.15);
  }

  // Broken markdown structure penalty
  const codeFenceCount = (content.match(/```/g) || []).length;
  if (codeFenceCount % 2 !== 0) score -= 0.10;

  // Excessive length without structure penalty
  if (wordCount > 1500 && headerCount < 3) score -= 0.05;

  return Math.max(0, Math.min(Math.round(score * 100) / 100, 1.0));
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
        const validation = validateContent(article.content, article.title);
        const qualityScore = calculateQualityScore(article.content, article.tags, validation);

        result = { classification, suggestedTags, qualityScore, validation };
        metadataUpdate = {
          classification: classification.type,
          complexity: classification.complexity,
          suggested_tags: suggestedTags,
          quality_score: qualityScore,
          word_count: article.content.split(/\s+/).length,
          validation_status: validation.is_valid ? 'valid' : 'has_errors',
          validation_errors: validation.error_count,
          validation_warnings: validation.warning_count
        };

        // Log validation issues
        if (validation.errors.length > 0) {
          console.log(`  ⚠️  ${validation.errors.length} error(s) found:`);
          validation.errors.slice(0, 3).forEach(e => console.log(`     - ${e.type}: ${e.message.substring(0, 60)}`));
        }
        if (validation.warnings.length > 0) {
          console.log(`  ℹ️  ${validation.warnings.length} warning(s) found`);
        }
        break;

      case 'validate':
        const fullValidation = validateContent(article.content, article.title);
        result = {
          is_valid: fullValidation.is_valid,
          errors: fullValidation.errors,
          warnings: fullValidation.warnings,
          summary: `${fullValidation.error_count} errors, ${fullValidation.warning_count} warnings`
        };
        metadataUpdate = {
          last_validated: new Date().toISOString(),
          validation_status: fullValidation.is_valid ? 'valid' : 'has_errors',
          validation_errors: fullValidation.error_count,
          validation_warnings: fullValidation.warning_count,
          validation_details: fullValidation
        };
        console.log(`  Validation: ${fullValidation.error_count} errors, ${fullValidation.warning_count} warnings`);
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
