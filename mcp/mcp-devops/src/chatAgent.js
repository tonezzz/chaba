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

const normalizeStep = (step) => {
  if (!step || typeof step !== 'object') return null;
  const workflowId = step.workflow_id || step.workflowId || step.id;
  if (!workflowId || typeof workflowId !== 'string') return null;
  const dryRun = step.dry_run ?? step.dryRun;
  return {
    workflow_id: workflowId,
    dry_run: Boolean(dryRun)
  };
};

export const planFromMessage = async ({ message, workflows, env }) => {
  const baseUrl =
    env.MCP_DEVOPS_LLM_BASE_URL ||
    env.GLAMA_API_URL ||
    env.GLAMA_URL ||
    '';
  const apiKey = env.MCP_DEVOPS_LLM_API_KEY || env.GLAMA_API_KEY || '';
  const model =
    env.MCP_DEVOPS_LLM_MODEL ||
    env.GLAMA_MODEL ||
    env.GLAMA_MODEL_LLM ||
    env.GLAMA_MODEL_DEFAULT ||
    '';
  const temperature = env.MCP_DEVOPS_LLM_TEMPERATURE ? Number(env.MCP_DEVOPS_LLM_TEMPERATURE) : 0;

  const workflowSummary = workflows
    .map((wf) => ({ id: wf.id, label: wf.label, description: wf.description, tags: wf.tags || [] }))
    .slice(0, 250);

  const system =
    'You are an operations planner for the repository automation server mcp-devops. ' +
    'You must output ONLY valid JSON. No markdown. No prose outside JSON. ' +
    'Choose workflows from the provided catalog. ' +
    'If you cannot find a suitable workflow, return an empty steps array and ask a clarifying question.';

  const user = {
    request: message,
    available_workflows: workflowSummary,
    required_output_schema: {
      type: 'object',
      properties: {
        summary: { type: 'string' },
        steps: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              workflow_id: { type: 'string' },
              dry_run: { type: 'boolean' }
            },
            required: ['workflow_id']
          }
        },
        requires_approval: { type: 'boolean' },
        questions: { type: 'array', items: { type: 'string' } }
      },
      required: ['summary', 'steps', 'requires_approval']
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

  const plan = extractJson(content);
  if (!plan || typeof plan !== 'object') {
    throw new Error('Failed to parse plan JSON from LLM response');
  }

  const steps = Array.isArray(plan.steps) ? plan.steps.map(normalizeStep).filter(Boolean) : [];

  return {
    summary: typeof plan.summary === 'string' ? plan.summary : '',
    steps,
    requires_approval: plan.requires_approval !== false,
    questions: Array.isArray(plan.questions) ? plan.questions.filter((q) => typeof q === 'string') : []
  };
};
