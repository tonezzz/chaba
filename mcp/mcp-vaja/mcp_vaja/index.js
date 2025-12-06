const path = require('path');
const fs = require('fs');
const express = require('express');
const cors = require('cors');
const dotenv = require('dotenv');

dotenv.config({ path: path.join(__dirname, '..', '.env') });

const {
  VAJA_SPEAKERS,
  requestVajaSpeech,
  downloadVajaAudio,
  DEFAULT_VAJA_ENDPOINT
} = require('../shared/tts/vajaClient');

const APP_NAME = 'mcp-vaja';
const APP_VERSION = '0.1.0';
const PORT = Number(process.env.PORT || 8017);
const OUTPUT_ROOT = process.env.VAJA_OUTPUT_DIR || path.join('/tmp', 'vaja-audio');

const ensureOutputDir = () => {
  if (!fs.existsSync(OUTPUT_ROOT)) {
    fs.mkdirSync(OUTPUT_ROOT, { recursive: true });
  }
};

const app = express();
app.use(cors());
app.use(express.json({ limit: process.env.JSON_BODY_LIMIT || '2mb' }));

const TOOL_SCHEMAS = {
  synthesize_speech: {
    name: 'synthesize_speech',
    description: 'Generate Thai speech audio via VAJA (AI4Thai).',
    input_schema: {
      type: 'object',
      required: ['text'],
      properties: {
        text: { type: 'string', minLength: 1, maxLength: 400 },
        speaker: { type: 'string', enum: VAJA_SPEAKERS.map((s) => s.id) },
        style: { type: 'string' },
        download: {
          type: 'boolean',
          description: 'If true, download audio locally and return file metadata.'
        }
      }
    }
  }
};

const validatePayload = (schemaName, payload) => {
  if (schemaName !== 'synthesize_speech') {
    return payload;
  }
  const errors = [];
  if (typeof payload.text !== 'string' || !payload.text.trim()) {
    errors.push('text is required');
  }
  if (payload.text && payload.text.length > 400) {
    errors.push('text must be <= 400 characters');
  }
  if (payload.speaker && !VAJA_SPEAKERS.some((s) => s.id === payload.speaker)) {
    errors.push(`unknown speaker '${payload.speaker}'`);
  }
  if (errors.length) {
    const error = new Error(errors.join(', '));
    error.status = 400;
    throw error;
  }
  return payload;
};

const synthesizeHandler = async (args = {}) => {
  const { text, speaker = 'noina', style, download = false } = args;
  validatePayload('synthesize_speech', args);

  const response = await requestVajaSpeech({
    text: text.trim(),
    speaker,
    style,
    endpoint: process.env.VAJA_ENDPOINT || DEFAULT_VAJA_ENDPOINT
  });

  const result = {
    msg: response.msg,
    audio_url: response.audio_url,
    speaker,
    style: style || null
  };

  if (download) {
    ensureOutputDir();
    const timestamp = Date.now();
    const filename = `${timestamp}-${speaker}.wav`;
    const destinationPath = path.join(OUTPUT_ROOT, filename);
    const downloadResult = await downloadVajaAudio({
      audioUrl: response.audio_url,
      destinationPath,
      onProgress: (progress) => {
        if (progress.totalBytes % 16384 === 0) {
          console.log(`[vaja] downloaded ${progress.totalBytes} bytes`);
        }
      }
    });
    result.download = {
      path: downloadResult.path,
      bytes: downloadResult.bytesWritten
    };
  }

  return result;
};

const TOOL_REGISTRY = {
  synthesize_speech: synthesizeHandler
};

const renderTestPage = () => {
  const speakerOptions = VAJA_SPEAKERS.map(
    (speaker) => `<option value="${speaker.id}">${speaker.description} (${speaker.id})</option>`
  ).join("");

  return `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>mcp-vaja • Test Console</title>
    <style>
      :root {
        color-scheme: light dark;
        font-family: "Inter", "Segoe UI", system-ui, -apple-system, sans-serif;
        background: radial-gradient(circle at top, #1f2433 0%, #0f1118 45%, #090b11 100%);
        color: #f5f5f7;
      }
      body {
        margin: 0;
        min-height: 100vh;
        display: flex;
        align-items: center;
        justify-content: center;
      }
      .card {
        width: min(560px, 94vw);
        border-radius: 20px;
        padding: 32px;
        background: rgba(15, 17, 24, 0.92);
        border: 1px solid rgba(255, 255, 255, 0.08);
        box-shadow: 0 20px 60px rgba(2, 4, 12, 0.65);
        backdrop-filter: blur(18px);
      }
      h1 {
        font-size: 1.5rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-top: 0;
      }
      h1 span {
        font-size: 0.85rem;
        font-weight: 500;
        color: #a0a7c1;
      }
      label {
        display: block;
        font-size: 0.9rem;
        margin-top: 18px;
        color: #c7cbe0;
      }
      textarea,
      select,
      input[type="text"] {
        width: 100%;
        margin-top: 8px;
        border-radius: 12px;
        border: 1px solid rgba(255, 255, 255, 0.15);
        background: rgba(255, 255, 255, 0.03);
        color: inherit;
        padding: 12px;
        font-size: 1rem;
      }
      textarea {
        min-height: 110px;
        resize: vertical;
      }
      button {
        margin-top: 24px;
        width: 100%;
        border: none;
        border-radius: 14px;
        padding: 14px;
        background: linear-gradient(120deg, #52b6ff, #687bff);
        color: #05060b;
        font-weight: 600;
        font-size: 1rem;
        cursor: pointer;
      }
      button:disabled {
        opacity: 0.6;
        cursor: not-allowed;
      }
      .output {
        margin-top: 20px;
        padding: 16px;
        border-radius: 14px;
        background: rgba(255, 255, 255, 0.04);
        border: 1px solid rgba(255, 255, 255, 0.08);
        font-size: 0.9rem;
        line-height: 1.4;
      }
      .inline-control {
        display: flex;
        gap: 12px;
        align-items: center;
        margin-top: 12px;
      }
      .inline-control label {
        margin: 0;
      }
    </style>
  </head>
  <body>
    <div class="card">
      <h1>
        mcp-vaja
        <span>/${APP_NAME}/www/test</span>
      </h1>
      <label>
        Text to synthesize
        <textarea id="text" placeholder="สวัสดีจาก mcp-vaja!"></textarea>
      </label>
      <label>
        Speaker
        <select id="speaker">
          ${speakerOptions}
        </select>
      </label>
      <label>
        Style (optional)
        <input type="text" id="style" placeholder="commercial, narrator, etc." />
      </label>
      <div class="inline-control">
        <input type="checkbox" id="download" />
        <label for="download">Download to server volume</label>
      </div>
      <button id="invokeBtn">Invoke tool</button>
      <div class="output" id="output">Waiting for input…</div>
    </div>

    <script>
      const outputEl = document.getElementById('output');
      const invokeBtn = document.getElementById('invokeBtn');

      const setOutput = (message, link) => {
        if (link) {
          outputEl.innerHTML = message + '<br /><a href="' + link + '" target="_blank" rel="noreferrer">Open audio ⤴</a>';
        } else {
          outputEl.textContent = message;
        }
      };

      invokeBtn.addEventListener('click', async () => {
        const text = document.getElementById('text').value.trim();
        const speaker = document.getElementById('speaker').value;
        const style = document.getElementById('style').value.trim();
        const download = document.getElementById('download').checked;

        if (!text) {
          setOutput('Please enter text before invoking.');
          return;
        }

        invokeBtn.disabled = true;
        setOutput('Invoking synthesize_speech…');

        try {
          const response = await fetch('/invoke', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              tool: 'synthesize_speech',
              arguments: { text, speaker, style: style || undefined, download }
            })
          });

          if (!response.ok) {
            const detail = await response.text();
            throw new Error(detail || 'Invocation failed');
          }

          const result = await response.json();
          const info = [
            'Speaker: ' + result.speaker,
            result.style ? 'Style: ' + result.style : null,
            result.download ? 'Saved to: ' + result.download.path : null
          ]
            .filter(Boolean)
            .join(' • ');
          setOutput('Success! ' + info, result.audio_url);
        } catch (err) {
          setOutput('Error: ' + err.message);
        } finally {
          invokeBtn.disabled = false;
        }
      });
    </script>
  </body>
</html>`;
};

app.get('/health', (_req, res) => {
  try {
    if (!process.env.AI4THAI_API_KEY) {
      return res.status(500).json({ status: 'error', detail: 'AI4THAI_API_KEY missing' });
    }
    return res.json({ status: 'ok', endpoint: process.env.VAJA_ENDPOINT || DEFAULT_VAJA_ENDPOINT });
  } catch (err) {
    return res.status(500).json({ status: 'error', detail: err.message });
  }
});

app.post('/invoke', async (req, res) => {
  const { tool, arguments: args = {} } = req.body || {};
  if (!tool || typeof tool !== 'string') {
    return res.status(400).json({ error: 'tool is required' });
  }
  const handler = TOOL_REGISTRY[tool];
  if (!handler) {
    return res.status(404).json({ error: `Unknown tool '${tool}'` });
  }

  try {
    const result = await handler(args);
    return res.json(result);
  } catch (err) {
    console.error('[mcp-vaja] invoke error', err);
    const status = err.status || 502;
    return res.status(status).json({ error: err.message || 'vaja_error' });
  }
});

app.get('/.well-known/mcp.json', (_req, res) => {
  res.json({
    name: APP_NAME,
    version: APP_VERSION,
    description: 'VAJA (AI4Thai) Text-to-Speech MCP provider',
    capabilities: {
      tools: Object.values(TOOL_SCHEMAS)
    }
  });
});

app.get('/www/test', (_req, res) => {
  res.type('html').send(renderTestPage());
});

app.listen(PORT, () => {
  console.log(`[mcp-vaja] listening on port ${PORT}`);
});
