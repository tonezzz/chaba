import { config } from './config.js';

const DEFAULT_TIMEOUT_MS = Number(process.env.MCP0_PROXY_TIMEOUT_MS || 20000);

const ensureFetch = () => {
  if (typeof fetch !== 'function') {
    throw new Error(
      'global fetch is unavailable. Run mcp-devops on Node.js 18+ or provide a fetch polyfill.'
    );
  }
  return fetch;
};

const buildProxyUrl = (provider, relativePath = '') => {
  if (!provider) {
    throw new Error('provider is required for MCP0 proxy requests');
  }
  const base = `${config.mcp0.baseUrl}/proxy/${provider.trim()}`;
  const cleanedPath = String(relativePath || '')
    .replace(/^\/*/, '')
    .replace(/\/*$/, '');
  return cleanedPath ? `${base}/${cleanedPath}` : base;
};

const parseResponseBody = async (response) => {
  const text = await response.text();
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
};

export const proxyProvider = async (
  provider,
  payload = {},
  { relativePath = '', timeoutMs = DEFAULT_TIMEOUT_MS, headers: extraHeaders = {} } = {}
) => {
  const fetchImpl = ensureFetch();
  const url = buildProxyUrl(provider, relativePath);
  const controller = new AbortController();
  const timeoutHandle = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetchImpl(url, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        ...(config.mcp0.adminToken ? { authorization: `Bearer ${config.mcp0.adminToken}` } : {}),
        ...extraHeaders
      },
      body: JSON.stringify(payload ?? {}),
      signal: controller.signal
    });

    const data = await parseResponseBody(response);

    if (!response.ok) {
      const detail = typeof data === 'string' ? data : JSON.stringify(data);
      throw new Error(`MCP0 proxy request failed (${response.status}): ${detail || 'unknown error'}`);
    }

    return {
      provider,
      status: response.status,
      data
    };
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new Error(`MCP0 proxy request timed out after ${timeoutMs} ms`);
    }
    throw error;
  } finally {
    clearTimeout(timeoutHandle);
  }
};

export const invokeDockerTool = async (tool, args = {}) => {
  if (!tool) {
    throw new Error('tool is required to invoke mcp-docker');
  }

  const payload = {
    tool: tool.trim(),
    arguments: args || {}
  };

  return proxyProvider(config.mcp0.dockerProvider, payload, { relativePath: 'invoke' });
};
