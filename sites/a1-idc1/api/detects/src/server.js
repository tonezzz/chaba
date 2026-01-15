import express from 'express';
import morgan from 'morgan';
import multer from 'multer';
import fetch from 'node-fetch';
import dotenv from 'dotenv';

dotenv.config();

const app = express();
const PORT = process.env.PORT || 4120;

const upload = multer({
  storage: multer.memoryStorage(),
  limits: {
    fileSize: 10 * 1024 * 1024 // 10 MB
  }
});

const trimMaybe = (value) => (typeof value === 'string' ? value.trim() : '');

const GLAMA_API_URL = (process.env.GLAMA_API_URL || process.env.GLAMA_URL || '').trim();
const GLAMA_API_KEY = (process.env.GLAMA_API_KEY || '').trim();
const DEFAULT_VISION_MODEL =
  trimMaybe(process.env.GLAMA_MODEL_VISION) ||
  trimMaybe(process.env.GLAMA_MODEL) ||
  trimMaybe(process.env.GLAMA_MODEL_DEFAULT) ||
  'gpt-4o-mini';
const DEFAULT_CHAT_MODEL =
  trimMaybe(process.env.GLAMA_MODEL_CHAT) ||
  trimMaybe(process.env.GLAMA_MODEL_LLM) ||
  trimMaybe(process.env.GLAMA_MODEL) ||
  trimMaybe(process.env.GLAMA_MODEL_DEFAULT) ||
  DEFAULT_VISION_MODEL;
const RAW_MODEL_LIST = (process.env.GLAMA_VISION_MODEL_LIST || '')
  .split(',')
  .map((value) => value.trim())
  .filter(Boolean);
const AVAILABLE_MODELS = Array.from(new Set([DEFAULT_VISION_MODEL, ...RAW_MODEL_LIST]));
const GLAMA_TEMPERATURE = Number.isFinite(Number(process.env.GLAMA_TEMPERATURE))
  ? Number(process.env.GLAMA_TEMPERATURE)
  : 0.1;
const GLAMA_MAX_TOKENS = Number.isFinite(Number(process.env.GLAMA_MAX_TOKENS))
  ? Number(process.env.GLAMA_MAX_TOKENS)
  : 800;
const SYSTEM_PROMPT =
  process.env.SYSTEM_PROMPT ||
  'You are Surf Thailand’s vision analyst. Reply strictly in JSON with keys description and objects.';
const CHAT_SYSTEM_PROMPT = (
  process.env.CHAT_SYSTEM_PROMPT ||
  'You are Surf Thailand’s vision follow-up analyst. Use the provided vision summary and detected objects to answer user questions in natural language. If you are unsure, say so. Reply in the same language as the user question.'
).trim();
const CHAT_TEMPERATURE = Number.isFinite(Number(process.env.GLAMA_CHAT_TEMPERATURE))
  ? Number(process.env.GLAMA_CHAT_TEMPERATURE)
  : 0.2;
const CHAT_MAX_TOKENS = Number.isFinite(Number(process.env.GLAMA_CHAT_MAX_TOKENS))
  ? Number(process.env.GLAMA_CHAT_MAX_TOKENS)
  : 600;

const isGlamaReady = () => Boolean(GLAMA_API_URL && GLAMA_API_KEY);

const ensureGlamaReady = (res) => {
  if (isGlamaReady()) {
    return true;
  }
  res.status(503).json({ error: 'glama_unconfigured' });
  return false;
};

const resolveModel = (requested) => {
  if (requested && AVAILABLE_MODELS.includes(requested)) {
    return requested;
  }
  return DEFAULT_VISION_MODEL;
};

const callVisionModel = async ({ prompt, base64Image, mimeType, model }) => {
  if (!isGlamaReady()) {
    throw new Error('glama_unconfigured');
  }
  const selectedModel = resolveModel(model);

  const messages = [
    {
      role: 'system',
      content: SYSTEM_PROMPT
    },
    {
      role: 'user',
      content: [
        {
          type: 'text',
          text: `${prompt}\nRespond as JSON {"description": "...", "objects":[{"label":"","confidence":0-1,"detail":""}]}.`
        },
        {
          type: 'image_url',
          image_url: {
            url: `data:${mimeType};base64,${base64Image}`
          }
        }
      ]
    }
  ];

  const payload = {
    model: selectedModel,
    temperature: GLAMA_TEMPERATURE,
    max_tokens: GLAMA_MAX_TOKENS,
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
  const rawContent = data?.choices?.[0]?.message?.content;
  const text =
    typeof rawContent === 'string'
      ? rawContent
      : Array.isArray(rawContent)
      ? rawContent
          .map((block) => {
            if (typeof block === 'string') return block;
            if (typeof block?.text === 'string') return block.text;
            if (typeof block?.content === 'string') return block.content;
            return '';
          })
          .join('\n')
          .trim()
      : '';

  return { data, text, model: selectedModel };
};

const callChatModel = async ({ messages, temperature = CHAT_TEMPERATURE, maxTokens = CHAT_MAX_TOKENS }) => {
  if (!isGlamaReady()) {
    throw new Error('glama_unconfigured');
  }
  if (!Array.isArray(messages) || !messages.length) {
    throw new Error('messages_required');
  }

  const payload = {
    model: DEFAULT_CHAT_MODEL,
    temperature,
    max_tokens: maxTokens,
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
  const rawContent = data?.choices?.[0]?.message?.content;
  const text =
    typeof rawContent === 'string'
      ? rawContent
      : Array.isArray(rawContent)
      ? rawContent
          .map((block) => {
            if (typeof block === 'string') return block;
            if (typeof block?.text === 'string') return block.text;
            if (typeof block?.content === 'string') return block.content;
            return '';
          })
          .join('\n')
          .trim()
      : '';

  return { data, text };
};

const sanitizeHistory = (history = []) => {
  if (!Array.isArray(history)) return [];
  return history
    .map((entry) => {
      if (!entry || typeof entry !== 'object') return null;
      const role = typeof entry.role === 'string' ? entry.role.trim().toLowerCase() : '';
      const content = typeof entry.content === 'string' ? entry.content.trim() : '';
      if (!role || !content) return null;
      if (!['user', 'assistant'].includes(role)) return null;
      return { role, content };
    })
    .filter(Boolean)
    .slice(-8);
};

app.use(morgan('dev'));
app.use(express.json({ limit: '1mb' }));

app.get('/health', (_req, res) => {
  res.json({
    status: isGlamaReady() ? 'ok' : 'degraded',
    model: DEFAULT_VISION_MODEL,
    models: AVAILABLE_MODELS,
    glamaReady: isGlamaReady(),
    timestamp: new Date().toISOString()
  });
});

app.get('/models', (_req, res) => {
  res.json({
    models: AVAILABLE_MODELS,
    default: DEFAULT_VISION_MODEL
  });
});

app.post('/analyze', upload.single('photo'), async (req, res) => {
  if (!ensureGlamaReady(res)) {
    return;
  }
  if (!req.file) {
    return res.status(400).json({ error: 'photo_required' });
  }
  const prompt = (req.body?.prompt || '').toString().trim();
  if (!prompt) {
    return res.status(400).json({ error: 'prompt_required' });
  }

  const mimeType = req.file.mimetype || 'image/jpeg';
  const base64Image = req.file.buffer.toString('base64');
  const startedAt = Date.now();
  const requestedModel = typeof req.body?.model === 'string' ? req.body.model.trim() : '';

  try {
    const { data, text, model } = await callVisionModel({
      prompt,
      base64Image,
      mimeType,
      model: requestedModel
    });
    const elapsed = Date.now() - startedAt;

    let parsed = null;
    if (text) {
      try {
        parsed = JSON.parse(text);
      } catch {
        const cleaned = text
          .trim()
          .replace(/```json/gi, '')
          .replace(/```/g, '')
          .trim();
        try {
          parsed = JSON.parse(cleaned);
        } catch {
          parsed = null;
        }
      }
    }

    const description = parsed?.description || text || 'No description returned.';
    const objects = Array.isArray(parsed?.objects) ? parsed.objects : [];

    res.json({
      description,
      objects,
      raw: data,
      model: model || data?.model || DEFAULT_VISION_MODEL,
      latencyMs: elapsed
    });
  } catch (error) {
    console.error('[detects-api] vision analyze failed', error);
    res.status(502).json({ error: error.message || 'glama_vision_failed' });
  }
});

app.post('/chat', async (req, res) => {
  if (!ensureGlamaReady(res)) {
    return;
  }
  const question = (req.body?.question || '').toString().trim();
  const description = (req.body?.description || '').toString().trim();
  const objects = Array.isArray(req.body?.objects) ? req.body.objects : [];
  const language = (req.body?.language || '').toString().trim();
  const history = sanitizeHistory(req.body?.history);

  if (!question) {
    return res.status(400).json({ error: 'question_required' });
  }
  if (!description && !objects.length) {
    return res.status(400).json({ error: 'context_required' });
  }

  const objectsText =
    objects
      .map((entry, index) => {
        if (!entry || typeof entry !== 'object') return null;
        const label = entry.label || `Object ${index + 1}`;
        const detail = entry.detail ? ` — ${entry.detail}` : '';
        const confidence =
          typeof entry.confidence === 'number' ? ` (confidence ${(entry.confidence * 100).toFixed(1)}%)` : '';
        return `• ${label}${detail}${confidence}`;
      })
      .filter(Boolean)
      .join('\n') || 'No objects were reported.';

  const contextBlock = `Vision summary:\n${description || 'N/A'}\n\nDetected objects:\n${objectsText}`;
  const localeHint = language ? ` [${language}]` : '';
  const userPrompt = `${contextBlock}\n\nQuestion${localeHint}:\n${question}`;

  const messages = [
    { role: 'system', content: CHAT_SYSTEM_PROMPT },
    ...history,
    { role: 'user', content: userPrompt }
  ];

  try {
    const { text } = await callChatModel({ messages });
    if (!text) {
      throw new Error('empty_response');
    }
    res.json({ reply: text });
  } catch (error) {
    console.error('[detects-api] chat failed', error);
    res.status(502).json({ error: error.message || 'glama_chat_failed' });
  }
});

app.use((_req, res) => {
  res.status(404).json({ error: 'not_found' });
});

app.listen(PORT, () => {
  console.log(`[detects-api] listening on port ${PORT}`);
});
