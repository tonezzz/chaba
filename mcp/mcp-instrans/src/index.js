import express from 'express';
import cors from 'cors';
import multer from 'multer';
import FormData from 'form-data';
import fetch from 'node-fetch';
import translate from '@vitalets/google-translate-api';
import { randomUUID } from 'crypto';
import path from 'path';
import { fileURLToPath } from 'url';
import fs from 'fs';
import pino from 'pino';

import {
  PORT,
  STT_URL,
  DEFAULT_TARGET_LANGUAGE,
  CLIENT_ORIGIN,
  SUMMARY_SENTENCE_LIMIT,
  SSE_HEARTBEAT_MS,
  AUDIO_CHUNK_LIMIT_BYTES,
  ENABLE_TRANSLATION,
  ENABLE_SUMMARIZER,
} from './config.js';

const logger = pino({ level: process.env.LOG_LEVEL || 'info' });

const app = express();
const jsonLimit = process.env.INSTRANS_JSON_LIMIT || '2mb';
const urlEncodedLimit = process.env.INSTRANS_URLENCODED_LIMIT || '2mb';

const allowedOrigins = CLIENT_ORIGIN === '*'
  ? true
  : CLIENT_ORIGIN.split(',').map((entry) => entry.trim()).filter(Boolean);

app.use(cors({ origin: allowedOrigins, credentials: true }));
app.use(express.json({ limit: jsonLimit }));
app.use(express.urlencoded({ limit: urlEncodedLimit, extended: true }));

const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: AUDIO_CHUNK_LIMIT_BYTES },
});

const sessions = new Map();
const sseClients = new Map();
const MAX_TRANSCRIPTS = Number(process.env.INSTRANS_MAX_TRANSCRIPTS || 200);

const TOOL_SCHEMAS = {
  start_session: {
    name: 'start_session',
    description: 'Create a new instruction+translation session',
    input_schema: {
      type: 'object',
      properties: {
        session_id: { type: 'string', description: 'Optional custom session identifier' },
        target_language: { type: 'string', description: 'Desired translation target language (ex: en)' }
      }
    }
  },
  list_sessions: {
    name: 'list_sessions',
    description: 'List current instrans sessions',
    input_schema: {
      type: 'object',
      properties: {}
    }
  },
  ingest_audio_base64: {
    name: 'ingest_audio_base64',
    description: 'Provide a base64-encoded audio chunk which will be transcribed + translated',
    input_schema: {
      type: 'object',
      required: ['session_id', 'audio_base64'],
      properties: {
        session_id: { type: 'string' },
        audio_base64: { type: 'string', description: 'Raw base64 or data URL encoded audio payload' },
        target_language: { type: 'string' },
        source_language: { type: 'string' },
        filename: { type: 'string' },
        speaker: { type: 'string' }
      }
    }
  }
};

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const staticDir = path.resolve(__dirname, '../public');
const indexHtmlPath = path.join(staticDir, 'index.html');

app.post('/invoke', async (req, res) => {
  const { tool, arguments: args = {} } = req.body || {};
  if (!tool || typeof tool !== 'string') {
    return res.status(400).json({ error: 'tool_required' });
  }
  const handler = TOOL_HANDLERS[tool];
  if (!handler) {
    return res.status(404).json({ error: `unknown_tool:${tool}` });
  }
  try {
    const result = await handler(args);
    return res.json({ tool, result });
  } catch (error) {
    logger.error({ error, tool }, '[instrans] invoke error');
    const status = error.status || 500;
    return res.status(status).json({ error: error.message || 'instrans_invoke_failed' });
  }
});

app.get('/.well-known/mcp.json', (_req, res) => {
  res.json({
    name: 'mcp-instrans',
    version: '0.1.0',
    description: 'Instruction + translation MCP provider',
    capabilities: {
      tools: Object.values(TOOL_SCHEMAS)
    }
  });
});

app.get('/health', (_req, res) => {
  res.json({
    status: 'ok',
    port: PORT,
    targetLanguage: DEFAULT_TARGET_LANGUAGE,
    sttUrl: STT_URL,
    translationEnabled: ENABLE_TRANSLATION,
    summaryEnabled: ENABLE_SUMMARIZER,
  });
});

app.post('/api/session', (req, res) => {
  try {
    const desiredLang = sanitizeLang(req.body?.targetLanguage) || DEFAULT_TARGET_LANGUAGE;
    const session = createSession(desiredLang);
    sessions.set(session.id, session);
    logger.info({ sessionId: session.id, targetLanguage: session.targetLanguage }, 'session created');
    res.json({ sessionId: session.id, session: serializeSession(session) });
  } catch (error) {
    logger.error(error, 'failed to create session');
    res.status(500).json({ error: 'session_create_failed' });
  }
});

app.patch('/api/session/:sessionId/target-language', async (req, res) => {
  const sessionId = String(req.params.sessionId || '').trim();
  const newLang = sanitizeLang(req.body?.targetLanguage);
  if (!sessionId) {
    return res.status(400).json({ error: 'session_id_required' });
  }
  if (!newLang) {
    return res.status(400).json({ error: 'target_language_required' });
  }

  const session = sessions.get(sessionId);
  if (!session) {
    return res.status(404).json({ error: 'session_not_found' });
  }

  try {
    session.targetLanguage = newLang;
    if (ENABLE_TRANSLATION && session.transcripts.length) {
      for (const entry of session.transcripts) {
        entry.translation = await translateText(entry.text, newLang);
        entry.targetLanguage = newLang;
      }
    }
    session.summary = buildSummary(session.transcripts);
    session.updatedAt = Date.now();
    broadcastSession(session);
    res.json({ session: serializeSession(session) });
  } catch (error) {
    logger.error({ error, sessionId, newLang }, 'failed to update target language');
    res.status(500).json({ error: 'target_language_update_failed' });
  }
});

app.get('/api/stream/:sessionId', (req, res) => {
  const sessionId = String(req.params.sessionId || '').trim();
  const session = sessions.get(sessionId);
  if (!session) {
    return res.status(404).json({ error: 'session_not_found' });
  }

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  if (allowedOrigins === true) {
    res.setHeader('Access-Control-Allow-Origin', '*');
  }
  res.flushHeaders?.();

  registerSseClient(sessionId, res);
  sendSse(res, 'session', serializeSession(session));

  const heartbeat = setInterval(() => {
    sendSse(res, 'heartbeat', { timestamp: Date.now() });
  }, SSE_HEARTBEAT_MS);

  req.on('close', () => {
    clearInterval(heartbeat);
    unregisterSseClient(sessionId, res);
    res.end();
  });
});

app.post('/api/chunk', upload.single('audio'), async (req, res) => {
  const sessionId = String(req.body?.sessionId || '').trim();
  const session = sessions.get(sessionId);
  if (!session) {
    return res.status(404).json({ error: 'session_not_found' });
  }

  if (!req.file) {
    return res.status(400).json({ error: 'audio_file_required' });
  }

  try {
    if (req.body?.targetLanguage) {
      const updated = sanitizeLang(req.body.targetLanguage);
      if (updated) {
        session.targetLanguage = updated;
      }
    }

    const sttResult = await transcribeWithWhisper(req.file, req.body?.sourceLanguage);
    const rawText = (sttResult?.text || '').trim();
    if (!rawText) {
      return res.status(422).json({ error: 'empty_transcript' });
    }

    const translation = await translateText(rawText, session.targetLanguage);
    const entry = buildTranscriptEntry({
      text: rawText,
      translation,
      detectedLanguage: sttResult?.language || 'auto',
      targetLanguage: session.targetLanguage,
    });

    session.transcripts.push(entry);
    if (session.transcripts.length > MAX_TRANSCRIPTS) {
      session.transcripts.splice(0, session.transcripts.length - MAX_TRANSCRIPTS);
    }
    session.summary = buildSummary(session.transcripts);
    session.updatedAt = Date.now();

    broadcastSession(session);
    res.json({ entry, session: serializeSession(session) });
  } catch (error) {
    logger.error({ error }, 'chunk processing failed');
    res.status(500).json({ error: 'chunk_processing_failed', detail: error.message });
  }
});

if (fs.existsSync(staticDir)) {
  app.use(express.static(staticDir));
}

app.get('*', (req, res, next) => {
  if (req.path.startsWith('/api')) {
    return next();
  }
  if (fs.existsSync(indexHtmlPath)) {
    return res.sendFile(indexHtmlPath);
  }
  return res.status(200).send('instrans UI not built yet. Run the client build first.');
});

app.listen(PORT, () => {
  logger.info({ port: PORT }, 'instrans service ready');
});

function createSession(targetLanguage) {
  return {
    id: randomUUID(),
    targetLanguage: targetLanguage || DEFAULT_TARGET_LANGUAGE,
    transcripts: [],
    summary: '',
    createdAt: Date.now(),
    updatedAt: Date.now(),
  };
}

function sanitizeLang(value) {
  return typeof value === 'string' ? value.trim().toLowerCase() : '';
}

async function transcribeWithWhisper(file, sourceLanguage) {
  const form = new FormData();
  form.append('file', file.buffer, {
    filename: file.originalname || `chunk-${Date.now()}.webm`,
    contentType: file.mimetype || 'audio/webm',
  });
  const normalized = sanitizeLang(sourceLanguage);
  if (normalized && normalized !== 'auto') {
    form.append('language', normalized);
  }
  const response = await fetch(`${STT_URL}/transcribe`, {
    method: 'POST',
    body: form,
    headers: form.getHeaders(),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`stt_failed: ${detail}`);
  }
  return response.json();
}

async function translateText(text, targetLanguage) {
  if (!ENABLE_TRANSLATION) {
    return text;
  }
  const trimmed = (text || '').trim();
  if (!trimmed) {
    return '';
  }
  const lang = sanitizeLang(targetLanguage) || DEFAULT_TARGET_LANGUAGE;
  if (lang === 'auto' || lang === '') {
    return trimmed;
  }
  try {
    const result = await translate(trimmed, { to: lang });
    return result?.text || trimmed;
  } catch (error) {
    logger.warn({ error }, 'translation failed, falling back to original text');
    return trimmed;
  }
}

function buildTranscriptEntry({ text, translation, detectedLanguage, targetLanguage }) {
  return {
    id: randomUUID(),
    text,
    translation,
    detectedLanguage,
    targetLanguage,
    timestamp: Date.now(),
  };
}

function buildSummary(entries) {
  if (!ENABLE_SUMMARIZER || !entries.length) {
    return '';
  }
  const recent = entries
    .map((entry) => entry.translation || entry.text)
    .filter(Boolean)
    .slice(-SUMMARY_SENTENCE_LIMIT);
  if (!recent.length) {
    return '';
  }
  return recent
    .map((line, index) => `${index + 1}. ${line}`)
    .join('\n');
}

function serializeSession(session) {
  return {
    id: session.id,
    targetLanguage: session.targetLanguage,
    summary: session.summary,
    transcripts: session.transcripts,
    updatedAt: session.updatedAt,
  };
}

function registerSseClient(sessionId, res) {
  const existing = sseClients.get(sessionId) || new Set();
  existing.add(res);
  sseClients.set(sessionId, existing);
}

function unregisterSseClient(sessionId, res) {
  const clients = sseClients.get(sessionId);
  if (!clients) {
    return;
  }
  clients.delete(res);
  if (!clients.size) {
    sseClients.delete(sessionId);
  }
}

function broadcastSession(session) {
  const clients = sseClients.get(session.id);
  if (!clients || !clients.size) {
    return;
  }
  const payload = JSON.stringify(serializeSession(session));
  for (const client of clients) {
    sendSse(client, 'session', payload, true);
  }
}

function sendSse(res, event, data, isSerialized = false) {
  const payload = isSerialized ? data : JSON.stringify(data);
  res.write(`event: ${event}\n`);
  res.write(`data: ${payload}\n\n`);
}

const TOOL_HANDLERS = {
  start_session: async (args = {}) => {
    const requestedId = typeof args.session_id === 'string' && args.session_id.trim() ? args.session_id.trim() : null;
    const targetLanguage = sanitizeLang(args.target_language || args.targetLanguage) || DEFAULT_TARGET_LANGUAGE;
    const session = createSession(targetLanguage);
    if (requestedId) {
      session.id = requestedId;
    }
    sessions.set(session.id, session);
    return serializeSession(session);
  },
  list_sessions: async () => {
    return {
      sessions: Array.from(sessions.values(), (session) => serializeSession(session))
    };
  },
  ingest_audio_base64: async (args = {}) => {
    const sessionId = requireString(args.session_id || args.sessionId, 'session_id');
    const session = sessions.get(sessionId);
    if (!session) {
      const error = new Error('session_not_found');
      error.status = 404;
      throw error;
    }
    const { buffer, filename, mimetype } = decodeBase64Audio(requireString(args.audio_base64 || args.audioBase64, 'audio_base64'), args.filename);
    const fakeFile = {
      buffer,
      originalname: filename,
      mimetype
    };
    const sttResult = await transcribeWithWhisper(fakeFile, args.source_language || args.sourceLanguage);
    const rawText = (sttResult?.text || '').trim();
    if (!rawText) {
      const error = new Error('empty_transcript');
      error.status = 422;
      throw error;
    }
    const langOverride = sanitizeLang(args.target_language || args.targetLanguage);
    if (langOverride) {
      session.targetLanguage = langOverride;
    }
    const translation = await translateText(rawText, session.targetLanguage);
    const entry = buildTranscriptEntry({
      text: rawText,
      translation,
      detectedLanguage: sttResult?.language || 'auto',
      targetLanguage: session.targetLanguage
    });
    session.transcripts.push(entry);
    if (session.transcripts.length > MAX_TRANSCRIPTS) {
      session.transcripts.splice(0, session.transcripts.length - MAX_TRANSCRIPTS);
    }
    session.summary = buildSummary(session.transcripts);
    session.updatedAt = Date.now();
    broadcastSession(session);
    return {
      entry,
      transcript: sttResult,
      session: serializeSession(session)
    };
  }
};

function requireString(value, field) {
  if (typeof value !== 'string' || !value.trim()) {
    const error = new Error(`${field}_required`);
    error.status = 400;
    throw error;
  }
  return value.trim();
}

function decodeBase64Audio(payload, filename) {
  let data = payload.trim();
  let mimetype = 'audio/webm';
  if (data.startsWith('data:')) {
    const commaIndex = data.indexOf(',');
    if (commaIndex > -1) {
      const meta = data.slice(5, commaIndex);
      const [type] = meta.split(';');
      if (type) {
        mimetype = type;
      }
      data = data.slice(commaIndex + 1);
    }
  }
  try {
    const buffer = Buffer.from(data, 'base64');
    return {
      buffer,
      filename: filename || `chunk-${Date.now()}.webm`,
      mimetype
    };
  } catch (error) {
    const err = new Error('audio_base64_invalid');
    err.status = 400;
    throw err;
  }
}
