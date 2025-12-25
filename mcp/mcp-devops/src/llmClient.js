const trimTrailingSlash = (value = '') => String(value).replace(/\/+$/, '');

const normalizeEndpoint = (baseUrl = '') => {
  const raw = String(baseUrl || '').trim();
  if (!raw) return '';
  if (/\/v1\/chat\/completions\/?$/i.test(raw)) {
    return raw;
  }
  return `${trimTrailingSlash(raw)}/v1/chat/completions`;
};

const normalizeHeaders = (headers = {}) => {
  const output = {};
  Object.entries(headers).forEach(([key, value]) => {
    if (value === undefined || value === null) return;
    output[key] = String(value);
  });
  return output;
};

export const callChatCompletions = async ({ baseUrl, apiKey, model, messages, temperature = 0 }) => {
  const url = normalizeEndpoint(baseUrl);
  if (!url) {
    throw new Error('Missing LLM endpoint (set MCP_DEVOPS_LLM_BASE_URL or GLAMA_API_URL)');
  }
  if (!model) {
    throw new Error('Missing model (set MCP_DEVOPS_LLM_MODEL or GLAMA_MODEL)');
  }

  const headers = normalizeHeaders({
    'Content-Type': 'application/json',
    ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {})
  });

  const response = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      model,
      messages,
      temperature
    })
  });

  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new Error(`LLM request failed (${response.status}): ${text || response.statusText}`);
  }

  const data = await response.json();
  const content = data?.choices?.[0]?.message?.content;
  if (!content || typeof content !== 'string') {
    throw new Error('LLM response missing choices[0].message.content');
  }

  return { content, raw: data };
};
