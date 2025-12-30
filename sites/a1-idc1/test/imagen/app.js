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
  rawOutput: document.getElementById('rawOutput'),
  imageUrlInput: document.getElementById('imageUrlInput'),
  copyJsonBtn: document.getElementById('copyJsonBtn'),
  copyImageUrlBtn: document.getElementById('copyImageUrlBtn'),
  openImageBtn: document.getElementById('openImageBtn'),
  downloadImageBtn: document.getElementById('downloadImageBtn'),
  refreshBackendBtn: document.getElementById('refreshBackendBtn')
};

const state = {
  isBusy: false,
  lastJsonText: '',
  lastImageUrl: ''
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
  const disabled = state.isBusy;
  if (els.copyJsonBtn) els.copyJsonBtn.disabled = disabled;
  if (els.copyImageUrlBtn) els.copyImageUrlBtn.disabled = disabled || !state.lastImageUrl;
  if (els.openImageBtn) els.openImageBtn.disabled = disabled || !state.lastImageUrl;
  if (els.downloadImageBtn) els.downloadImageBtn.disabled = disabled || !state.lastImageUrl;
  if (els.refreshBackendBtn) els.refreshBackendBtn.disabled = disabled;
};

const setResultJson = (payload) => {
  const text = payload ? JSON.stringify(payload, null, 2) : '';
  state.lastJsonText = text;
  if (els.rawOutput) {
    els.rawOutput.textContent = text || '// Awaiting response…';
  }
};

const setImageUrl = (url) => {
  state.lastImageUrl = typeof url === 'string' ? url : '';
  if (els.imageUrlInput) {
    els.imageUrlInput.value = state.lastImageUrl;
  }
  // keep toolbar state in sync
  setBusy(state.isBusy);
};

const parseErrorHint = (payload) => {
  if (!payload || typeof payload !== 'object') return '';
  const hints = Array.isArray(payload.hints) ? payload.hints.filter(Boolean) : [];
  if (hints.length) return hints.join(' ');
  if (typeof payload.error === 'string' && payload.error.trim()) return payload.error.trim();
  if (typeof payload.detail === 'string' && payload.detail.trim()) return payload.detail.trim();
  return '';
};

const copyText = async (text) => {
  const value = (text || '').trim();
  if (!value) return false;
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    return false;
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
    setImageUrl('');
    return;
  }
  els.resultImage.src = dataUrl;
  els.resultImage.classList.remove('hidden');
  els.imagePlaceholder.classList.add('hidden');
  setImageUrl(dataUrl);
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

const refreshBackend = async () => {
  setStatus('Refreshing backend status…');
  await probeBackend();
  setStatus('Backend status refreshed.');
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
  setResultJson(null);

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

    setResultJson(data);

    if (!response.ok) {
      const hint = parseErrorHint(data);
      setStatus(`Generation failed (HTTP ${response.status}).${hint ? ` ${hint}` : ''}`);
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

  if (els.copyJsonBtn) {
    els.copyJsonBtn.addEventListener('click', async () => {
      if (!state.lastJsonText) return;
      const ok = await copyText(state.lastJsonText);
      setStatus(ok ? 'Copied JSON to clipboard.' : 'Copy failed (clipboard permission denied).');
    });
  }

  if (els.copyImageUrlBtn) {
    els.copyImageUrlBtn.addEventListener('click', async () => {
      if (!state.lastImageUrl) return;
      const ok = await copyText(state.lastImageUrl);
      setStatus(ok ? 'Copied image URL to clipboard.' : 'Copy failed (clipboard permission denied).');
    });
  }

  if (els.openImageBtn) {
    els.openImageBtn.addEventListener('click', () => {
      if (!state.lastImageUrl) return;
      window.open(state.lastImageUrl, '_blank', 'noopener,noreferrer');
    });
  }

  if (els.downloadImageBtn) {
    els.downloadImageBtn.addEventListener('click', () => {
      if (!state.lastImageUrl) return;
      const a = document.createElement('a');
      a.href = state.lastImageUrl;
      a.download = 'imagen.png';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    });
  }

  if (els.refreshBackendBtn) {
    els.refreshBackendBtn.addEventListener('click', () => {
      if (state.isBusy) return;
      refreshBackend();
    });
  }

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
