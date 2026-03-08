import { callChatCompletions } from './llmClient.js';

const safeJsonParse = (text) => {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
};

const extractJson = (text = '') => {
  const raw = String(text).trim();
  const direct = safeJsonParse(raw);
  if (direct) return direct;

  const fenceMatch = raw.match(/```json\s*([\s\S]*?)\s*```/i);
  if (fenceMatch?.[1]) {
    const fenced = safeJsonParse(fenceMatch[1].trim());
    if (fenced) return fenced;
  }

  const first = raw.indexOf('{');
  const last = raw.lastIndexOf('}');
  if (first >= 0 && last > first) {
    const sliced = safeJsonParse(raw.slice(first, last + 1));
    if (sliced) return sliced;
  }

  return null;
};

const getLlmConfig = (env) => ({
  baseUrl: env.MCP_CODING_AGENT_LLM_BASE_URL || env.GLAMA_API_URL || env.GLAMA_URL || '',
  apiKey: env.MCP_CODING_AGENT_LLM_API_KEY || env.GLAMA_API_KEY || '',
  model:
    env.MCP_CODING_AGENT_LLM_MODEL ||
    env.GLAMA_MODEL ||
    env.GLAMA_MODEL_LLM ||
    env.GLAMA_MODEL_DEFAULT ||
    '',
  temperature: env.MCP_CODING_AGENT_LLM_TEMPERATURE ? Number(env.MCP_CODING_AGENT_LLM_TEMPERATURE) : 0
});

export const analyzeCode = async ({ code, language, question, env }) => {
  const { baseUrl, apiKey, model, temperature } = getLlmConfig(env);

  const langHint = language ? ` The code is written in ${language}.` : '';
  const questionHint = question ? ` Focus on: ${question}` : '';

  const system =
    'You are an expert software engineer and code reviewer. ' +
    'Analyze the provided code and output ONLY valid JSON with no markdown prose outside the JSON object. ' +
    'Identify bugs, potential errors, security issues, performance problems, and style improvements.';

  const user = {
    task: 'analyze_code',
    code,
    language: language || 'unknown',
    question: question || 'Perform a general analysis.',
    required_output_schema: {
      type: 'object',
      properties: {
        summary: { type: 'string', description: 'Brief overall assessment of the code.' },
        bugs: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              line: { type: 'number', description: 'Approximate line number (0 if unknown).' },
              severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low', 'info'] },
              description: { type: 'string' },
              suggestion: { type: 'string' }
            },
            required: ['severity', 'description']
          }
        },
        security_issues: {
          type: 'array',
          items: { type: 'object', properties: { description: { type: 'string' }, suggestion: { type: 'string' } } }
        },
        improvements: { type: 'array', items: { type: 'string' } },
        overall_score: {
          type: 'number',
          description: 'Quality score 1–10 (10 = excellent).'
        }
      },
      required: ['summary', 'bugs', 'overall_score']
    }
  };

  const hint = `${langHint}${questionHint}`;
  const { content } = await callChatCompletions({
    baseUrl,
    apiKey,
    model,
    temperature,
    messages: [
      { role: 'system', content: system + (hint ? ` ${hint.trim()}` : '') },
      { role: 'user', content: JSON.stringify(user) }
    ]
  });

  const result = extractJson(content);
  if (!result || typeof result !== 'object') {
    throw new Error('Failed to parse analysis JSON from LLM response');
  }

  return {
    summary: typeof result.summary === 'string' ? result.summary : '',
    bugs: Array.isArray(result.bugs) ? result.bugs : [],
    security_issues: Array.isArray(result.security_issues) ? result.security_issues : [],
    improvements: Array.isArray(result.improvements) ? result.improvements : [],
    overall_score: typeof result.overall_score === 'number' ? result.overall_score : null
  };
};

export const fixBugs = async ({ code, language, error_message, description, env }) => {
  const { baseUrl, apiKey, model, temperature } = getLlmConfig(env);

  const system =
    'You are an expert software engineer and debugger. ' +
    'Fix the bugs in the provided code and output ONLY valid JSON with no markdown prose outside the JSON object. ' +
    'Preserve the original intent and style of the code as much as possible.';

  const user = {
    task: 'fix_bugs',
    code,
    language: language || 'unknown',
    error_message: error_message || null,
    description: description || 'Fix all bugs and issues in the code.',
    required_output_schema: {
      type: 'object',
      properties: {
        fixed_code: { type: 'string', description: 'The corrected code.' },
        changes: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              line: { type: 'number', description: 'Approximate line number (0 if unknown).' },
              original: { type: 'string', description: 'Original code fragment.' },
              fixed: { type: 'string', description: 'Fixed code fragment.' },
              reason: { type: 'string', description: 'Why this change was made.' }
            },
            required: ['fixed', 'reason']
          }
        },
        explanation: { type: 'string', description: 'Overall explanation of what was fixed and why.' }
      },
      required: ['fixed_code', 'changes', 'explanation']
    }
  };

  const { content } = await callChatCompletions({
    baseUrl,
    apiKey,
    model,
    temperature,
    messages: [
      { role: 'system', content: system },
      { role: 'user', content: JSON.stringify(user) }
    ]
  });

  const result = extractJson(content);
  if (!result || typeof result !== 'object') {
    throw new Error('Failed to parse fix JSON from LLM response');
  }

  return {
    fixed_code: typeof result.fixed_code === 'string' ? result.fixed_code : '',
    changes: Array.isArray(result.changes) ? result.changes : [],
    explanation: typeof result.explanation === 'string' ? result.explanation : ''
  };
};

export const reviewCode = async ({ code, language, context, env }) => {
  const { baseUrl, apiKey, model, temperature } = getLlmConfig(env);

  const system =
    'You are a senior software engineer performing a thorough code review. ' +
    'Output ONLY valid JSON with no markdown prose outside the JSON object. ' +
    'Be constructive, specific, and actionable in your feedback.';

  const user = {
    task: 'review_code',
    code,
    language: language || 'unknown',
    context: context || null,
    required_output_schema: {
      type: 'object',
      properties: {
        verdict: {
          type: 'string',
          enum: ['approve', 'approve_with_suggestions', 'request_changes'],
          description: 'Overall review verdict.'
        },
        summary: { type: 'string', description: 'High-level review summary.' },
        comments: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              line: { type: 'number', description: 'Approximate line number (0 if unknown).' },
              type: {
                type: 'string',
                enum: ['bug', 'security', 'performance', 'style', 'suggestion', 'praise']
              },
              comment: { type: 'string' },
              suggested_change: { type: 'string', description: 'Optional improved snippet.' }
            },
            required: ['type', 'comment']
          }
        },
        positives: { type: 'array', items: { type: 'string' }, description: 'Things done well.' },
        overall_score: { type: 'number', description: 'Quality score 1–10 (10 = excellent).' }
      },
      required: ['verdict', 'summary', 'comments', 'overall_score']
    }
  };

  const { content } = await callChatCompletions({
    baseUrl,
    apiKey,
    model,
    temperature,
    messages: [
      { role: 'system', content: system },
      { role: 'user', content: JSON.stringify(user) }
    ]
  });

  const result = extractJson(content);
  if (!result || typeof result !== 'object') {
    throw new Error('Failed to parse review JSON from LLM response');
  }

  return {
    verdict: typeof result.verdict === 'string' ? result.verdict : 'approve_with_suggestions',
    summary: typeof result.summary === 'string' ? result.summary : '',
    comments: Array.isArray(result.comments) ? result.comments : [],
    positives: Array.isArray(result.positives) ? result.positives : [],
    overall_score: typeof result.overall_score === 'number' ? result.overall_score : null
  };
};
