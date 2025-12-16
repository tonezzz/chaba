import path from 'path';
import express from 'express';
import morgan from 'morgan';
import fetch from 'node-fetch';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = process.env.PORT || 4020;

const GLAMA_API_URL = (process.env.GLAMA_API_URL || process.env.GLAMA_URL || '').trim();
const GLAMA_API_KEY = (process.env.GLAMA_API_KEY || '').trim();
const GLAMA_MODEL =
  (process.env.GLAMA_MODEL || process.env.GLAMA_MODEL_LLM || process.env.GLAMA_MODEL_DEFAULT || '').trim() ||
  'gpt-4o-mini';
const GLAMA_MODEL_LIST = (process.env.GLAMA_MODEL_LIST || '').trim();
const GLAMA_TEMPERATURE = Number.isFinite(Number(process.env.GLAMA_TEMPERATURE))
  ? Number(process.env.GLAMA_TEMPERATURE)
  : 0.2;
const GLAMA_MAX_TOKENS = Number.isFinite(Number(process.env.GLAMA_MAX_TOKENS))
  ? Number(process.env.GLAMA_MAX_TOKENS)
  : 800;
const SYSTEM_PROMPT =
  (process.env.SYSTEM_PROMPT ||
    'You are a concise assistant helping Surf Thailand test Glama on a1.idc1. Keep replies focused and upbeat.').trim();

const isGlamaReady = () => Boolean(GLAMA_API_KEY && GLAMA_API_URL);

const getModelAllowlist = () => {
  const fallback = [GLAMA_MODEL, 'gpt-4o', 'gpt-4.1'];
  const fromEnv = GLAMA_MODEL_LIST
    ? GLAMA_MODEL_LIST.split(',')
        .map((item) => item.trim())
        .filter(Boolean)
    : [];
  const merged = [...new Set([...fromEnv, ...fallback])];
  return merged;
};

const resolveRequestedModel = (requestedModel) => {
  const allowlist = getModelAllowlist();
  if (typeof requestedModel !== 'string' || !requestedModel.trim()) {
    return GLAMA_MODEL;
  }
  const model = requestedModel.trim();
  return allowlist.includes(model) ? model : GLAMA_MODEL;
};

const ensureGlamaReady = (res) => {
  if (!isGlamaReady()) {
    res.status(503).json({ error: 'glama_unconfigured' });
    return false;
  }
  return true;
};

const sanitizeHistory = (history = []) => {
  if (!Array.isArray(history)) return [];
  return history
    .map((entry) => {
      const role = typeof entry?.role === 'string' ? entry.role.trim().toLowerCase() : '';
      const content = typeof entry?.content === 'string' ? entry.content.trim() : '';
      if (!role || !content) return null;
      if (!['user', 'assistant', 'system'].includes(role)) return null;
      return { role, content };
    })
    .filter(Boolean)
    .slice(-12);
};

const callGlamaChatCompletion = async ({ messages, maxTokens, temperature, model }) => {
  if (!isGlamaReady()) {
    throw new Error('glama_unconfigured');
  }
  if (!Array.isArray(messages) || !messages.length) {
    throw new Error('messages_required');
  }

  const payload = {
    model: resolveRequestedModel(model),
    max_tokens: Number.isFinite(maxTokens) && maxTokens > 0 ? maxTokens : GLAMA_MAX_TOKENS,
    temperature: typeof temperature === 'number' ? temperature : GLAMA_TEMPERATURE,
    messages
  };

  const response = await fetch(GLAMA_API_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${GLAMA_API_KEY}`
    },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `glama_http_${response.status}`);
  }

  const data = await response.json();
  const text = Array.isArray(data?.choices)
    ? data.choices
        .map((choice) => choice?.message?.content || '')
        .filter(Boolean)
        .join('\n')
        .trim()
    : '';

  return { text, data };
};

app.use(morgan('dev'));
app.use(express.json());
app.use(express.static(path.join(__dirname, '..', '..', 'test', 'chat')));

app.get('/api/health', (_req, res) => {
  const modelAllowlist = getModelAllowlist();
  res.json({
    status: isGlamaReady() ? 'ok' : 'degraded',
    glamaReady: isGlamaReady(),
    model: GLAMA_MODEL,
    modelAllowlist,
    timestamp: new Date().toISOString()
  });
});

const sanitizeAttachments = (attachments = []) => {
  if (!Array.isArray(attachments)) return [];
  return attachments
    .map((item) => {
      const kind = typeof item?.kind === 'string' ? item.kind.trim().toLowerCase() : '';
      const name = typeof item?.name === 'string' ? item.name.trim() : '';
      const dataUrl = typeof item?.dataUrl === 'string' ? item.dataUrl.trim() : '';
      if (kind !== 'image') return null;
      if (!dataUrl.startsWith('data:image/')) return null;
      return { kind, name, dataUrl };
    })
    .filter(Boolean)
    .slice(0, 3);
};

app.post('/api/chat', async (req, res) => {
  if (!ensureGlamaReady(res)) {
    return;
  }

  const { message, history = [], temperature, model, attachments = [] } = req.body || {};
  if (typeof message !== 'string' || !message.trim()) {
    return res.status(400).json({ error: 'message_required' });
  }

  const sanitizedHistory = sanitizeHistory(history);
  const sanitizedAttachments = sanitizeAttachments(attachments);
  const userContent = sanitizedAttachments.length
    ? [
        { type: 'text', text: message.trim() },
        ...sanitizedAttachments.map((item) => ({
          type: 'image_url',
          image_url: { url: item.dataUrl }
        }))
      ]
    : message.trim();

  const messages = [{ role: 'system', content: SYSTEM_PROMPT }, ...sanitizedHistory, { role: 'user', content: userContent }];

  try {
    const resolvedModel = resolveRequestedModel(model);
    const { text, data } = await callGlamaChatCompletion({ messages, temperature, model: resolvedModel });
    if (!text) {
      return res.status(502).json({ error: 'empty_response' });
    }
    return res.json({ reply: text, usage: data?.usage ?? null, model: data?.model || resolvedModel });
  } catch (error) {
    console.error('[glama-api] chat failed', error);
    return res.status(502).json({ error: error.message || 'glama_chat_failed' });
  }
});

app.use((req, res, next) => {
  if (req.method !== 'GET') return next();
  res.sendFile(path.join(__dirname, '..', '..', 'test', 'chat', 'index.html'));
});

app.listen(PORT, () => {
  console.log(`[glama-api] listening on port ${PORT}`);
});
