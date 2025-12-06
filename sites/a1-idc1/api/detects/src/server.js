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

const GLAMA_API_URL = (process.env.GLAMA_API_URL || process.env.GLAMA_URL || '').trim();
const GLAMA_API_KEY = (process.env.GLAMA_API_KEY || '').trim();
const DEFAULT_VISION_MODEL =
  (process.env.GLAMA_MODEL_VISION || process.env.GLAMA_MODEL || process.env.GLAMA_MODEL_DEFAULT || '').trim() ||
  'gpt-4o-mini';
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

app.use(morgan('dev'));

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

app.use((_req, res) => {
  res.status(404).json({ error: 'not_found' });
});

app.listen(PORT, () => {
  console.log(`[detects-api] listening on port ${PORT}`);
});
