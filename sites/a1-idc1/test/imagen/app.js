const API_BASE = '/test/imagen/api';

const PROMPT_PRESETS = [
  {
    label: 'Verification badge',
    prompt: 'vibrant MCP stack verification badge, flat illustration'
  },
  {
    label: 'Thai surf poster',
    prompt: 'retro Thai surf poster, warm sunset gradient, halftone texture'
  },
  {
    label: 'Product mock',
    prompt: 'minimal product mock photo, soft studio light, pastel background'
  },
  {
    label: 'Cyber schematic',
    prompt: 'futuristic technical schematic, neon blueprint lines on dark background'
  }
];

const els = {
  backendStatus: document.getElementById('backendStatus'),
  latencyTag: document.getElementById('latencyTag'),
  form: document.getElementById('generateForm'),
  promptInput: document.getElementById('promptInput'),
  promptChips: document.getElementById('promptChips'),
  widthInput: document.getElementById('widthInput'),
  heightInput: document.getElementById('heightInput'),
  stepsInput: document.getElementById('stepsInput'),
  seedInput: document.getElementById('seedInput'),
  statusBanner: document.getElementById('statusBanner'),
  generateBtn: document.getElementById('generateBtn'),
  imageWrap: document.getElementById('imageWrap'),
  imagePlaceholder: document.getElementById('imagePlaceholder'),
  resultImage: document.getElementById('resultImage'),
  rawOutput: document.getElementById('rawOutput')
};

const state = {
  isBusy: false
};

const setStatus = (text) => {
  if (els.statusBanner) {
    els.statusBanner.textContent = text;
  }
};

const setBackend = (text) => {
  if (els.backendStatus) {
    els.backendStatus.textContent = text;
  }
};

const setLatency = (ms) => {
  if (!els.latencyTag) return;
  els.latencyTag.textContent = Number.isFinite(ms) ? `${ms} ms` : '—';
};

const setBusy = (busy) => {
  state.isBusy = Boolean(busy);
  if (els.generateBtn) {
    els.generateBtn.disabled = state.isBusy;
    els.generateBtn.textContent = state.isBusy ? 'Generating…' : 'Generate';
  }
};

const safeJson = async (response) => {
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    return await response.json();
  }
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    return { raw: text };
  }
};

const renderPresets = () => {
  if (!els.promptChips) return;
  els.promptChips.innerHTML = '';
  PROMPT_PRESETS.forEach((preset) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = preset.label;
    button.addEventListener('click', () => {
      els.promptInput.value = preset.prompt;
      els.promptInput.focus();
      setStatus('Preset loaded. Ready to generate.');
    });
    els.promptChips.appendChild(button);
  });
};

const showImageDataUrl = (dataUrl) => {
  if (!els.resultImage || !els.imagePlaceholder) return;
  if (!dataUrl) {
    els.resultImage.classList.add('hidden');
    els.imagePlaceholder.classList.remove('hidden');
    els.imagePlaceholder.textContent = 'No image returned.';
    return;
  }
  els.resultImage.src = dataUrl;
  els.resultImage.classList.remove('hidden');
  els.imagePlaceholder.classList.add('hidden');
};

const tryExtractAdapterImage = (payload) => {
  if (!payload || typeof payload !== 'object') return null;
  const direct = payload.image_data_url;
  if (typeof direct === 'string' && direct.trim()) {
    return direct.trim();
  }
  return null;
};

const tryExtractImage = (payload) => {
  if (!payload || typeof payload !== 'object') return null;

  // Common patterns we might see from an image service.
  const direct = payload.image || payload.image_base64 || payload.base64 || null;
  if (typeof direct === 'string' && direct.trim()) {
    const value = direct.trim();
    if (value.startsWith('data:image/')) {
      return value;
    }
    // Assume raw base64; default to png.
    return `data:image/png;base64,${value}`;
  }

  const first =
    (Array.isArray(payload.images) && payload.images[0]) ||
    (Array.isArray(payload.outputs) && payload.outputs[0]) ||
    (Array.isArray(payload.data) && payload.data[0]) ||
    null;

  if (typeof first === 'string' && first.trim()) {
    const value = first.trim();
    if (value.startsWith('data:image/')) {
      return value;
    }
    return `data:image/png;base64,${value}`;
  }

  if (first && typeof first === 'object') {
    const inner = first.base64 || first.image || first.image_base64 || first.url;
    if (typeof inner === 'string' && inner.trim()) {
      const value = inner.trim();
      if (value.startsWith('data:image/')) {
        return value;
      }
      if (value.startsWith('http://') || value.startsWith('https://')) {
        return value;
      }
      return `data:image/png;base64,${value}`;
    }
  }

  return null;
};

const probeBackend = async () => {
  setBackend('Checking…');
  setLatency(null);
  try {
    const started = performance.now();
    const response = await fetch(`${API_BASE}/health`);
    const elapsed = Math.round(performance.now() - started);
    setLatency(elapsed);

    if (!response.ok) {
      setBackend(`HTTP ${response.status}`);
      return;
    }

    const data = await safeJson(response);
    const status =
      (data && (data.status || data.state || data.health)) ||
      (typeof data === 'string' ? data : 'ok');
    setBackend(String(status).slice(0, 48));
  } catch (err) {
    setBackend(err?.message || 'error');
  }
};

const buildGeneratePayload = () => {
  const prompt = (els.promptInput?.value || '').trim();
  const width = Number.parseInt(els.widthInput?.value, 10);
  const height = Number.parseInt(els.heightInput?.value, 10);
  const num_inference_steps = Number.parseInt(els.stepsInput?.value, 10);
  const seedRaw = (els.seedInput?.value || '').trim();

  const payload = {
    prompt,
    width: Number.isFinite(width) ? width : 512,
    height: Number.isFinite(height) ? height : 512,
    num_inference_steps: Number.isFinite(num_inference_steps) ? num_inference_steps : 8
  };

  if (seedRaw) {
    const seed = Number.parseInt(seedRaw, 10);
    if (Number.isFinite(seed)) {
      payload.seed = seed;
    }
  }

  return payload;
};

const generateImage = async () => {
  const payload = buildGeneratePayload();

  if (!payload.prompt) {
    setStatus('Please enter a prompt.');
    return;
  }

  setBusy(true);
  setStatus('Generating image…');
  showImageDataUrl(null);
  if (els.rawOutput) {
    els.rawOutput.textContent = '// Awaiting response…';
  }

  try {
    const started = performance.now();
    const response = await fetch(`${API_BASE}/generate`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const elapsed = Math.round(performance.now() - started);
    setLatency(elapsed);

    const data = await safeJson(response);

    if (els.rawOutput) {
      els.rawOutput.textContent = JSON.stringify(data, null, 2);
    }

    if (!response.ok) {
      setStatus(`Generation failed (HTTP ${response.status}).`);
      return;
    }

    const image = tryExtractAdapterImage(data) || tryExtractImage(data);
    if (image) {
      showImageDataUrl(image);
      setStatus('Done.');
    } else {
      showImageDataUrl(null);
      setStatus('Done (no image field detected in response).');
    }
  } catch (err) {
    setStatus(`Generation failed: ${err?.message || 'unknown error'}`);
  } finally {
    setBusy(false);
  }
};

const main = () => {
  renderPresets();
  probeBackend();
  setStatus('Waiting for a prompt…');

  if (els.form) {
    els.form.addEventListener('submit', (event) => {
      event.preventDefault();
      if (!state.isBusy) {
        generateImage();
      }
    });
  }
};

main();
