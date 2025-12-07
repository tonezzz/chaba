const API_BASE = '/test/imagen/api';

const $ = (selector) => document.querySelector(selector);
const healthStatusEl = $('#healthStatus');
const lastDurationEl = $('#lastDuration');
const healthRefreshBtn = $('#healthRefresh');
const form = $('#generateForm');
const promptInput = $('#promptInput');
const negativeInput = $('#negativeInput');
const stepsInput = $('#stepsInput');
const guidanceInput = $('#guidanceInput');
const stepsValueEl = $('#stepsValue');
const guidanceValueEl = $('#guidanceValue');
const sizeSelect = $('#sizeSelect');
const seedInput = $('#seedInput');
const statusBanner = $('#formStatus');
const previewWrapper = $('#previewWrapper');
const resultImage = $('#resultImage');
const metaList = $('#metaList');
const rawOutput = $('#rawOutput');
const logList = $('#logList');
const clearLogsBtn = $('#clearLogs');
const generateBtn = $('#generateBtn');

const formatDuration = (ms) => {
  if (!Number.isFinite(ms)) return '—';
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
};

const addLog = (message, tone = 'info') => {
  if (!logList) return;
  const item = document.createElement('li');
  item.textContent = `${new Date().toLocaleTimeString()} · ${message}`;
  if (tone === 'success') item.classList.add('success');
  if (tone === 'error') item.classList.add('error');
  logList.prepend(item);
  const excess = [...logList.children].slice(50);
  excess.forEach((node) => node.remove());
};

const setStatus = (text, ok = false) => {
  if (!statusBanner) return;
  statusBanner.textContent = text;
  statusBanner.classList.toggle('ok', ok);
};

const setFormBusy = (busy) => {
  if (generateBtn) {
    generateBtn.disabled = busy;
    generateBtn.textContent = busy ? 'Rendering…' : 'Generate preview';
  }
};

const updateStepsLabel = () => {
  if (stepsValueEl) {
    stepsValueEl.textContent = `${stepsInput.value} steps`;
  }
};

const updateGuidanceLabel = () => {
  if (guidanceValueEl) {
    guidanceValueEl.textContent = `${Number(guidanceInput.value).toFixed(1)} CFG`;
  }
};

const renderMeta = (data) => {
  if (!metaList) return;
  metaList.innerHTML = '';
  const pairs = [
    ['Prompt', data.prompt],
    ['Negative', data.negative_prompt || '—'],
    ['Steps', data.num_inference_steps],
    ['Guidance', data.guidance_scale],
    ['Width', data.width],
    ['Height', data.height],
    ['Seed', data.seed ?? 'random'],
    ['Device', data.device || data.accelerator || '—']
  ];
  pairs.forEach(([label, value]) => {
    const dt = document.createElement('dt');
    dt.textContent = label;
    const dd = document.createElement('dd');
    dd.textContent = value ?? '—';
    metaList.append(dt, dd);
  });
};

const setPreview = (imageBase64) => {
  if (!previewWrapper || !resultImage) return;
  if (imageBase64) {
    resultImage.src = imageBase64;
    previewWrapper.hidden = false;
  } else {
    previewWrapper.hidden = true;
  }
};

const setRawOutput = (payload) => {
  if (!rawOutput) return;
  rawOutput.textContent = JSON.stringify(payload, null, 2);
};

const fetchJson = async (path, options = {}) => {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(data?.error || response.statusText || 'request_failed');
    error.payload = data;
    throw error;
  }
  return data;
};

const runHealthCheck = async () => {
  try {
    healthStatusEl.textContent = 'Checking…';
    const data = await fetchJson('/health', { method: 'GET' });
    healthStatusEl.textContent = data.status || 'ok';
    addLog('Health OK', 'success');
  } catch (error) {
    const detail = error?.payload?.detail || error.message;
    healthStatusEl.textContent = 'error';
    addLog(`Health failed: ${detail}`, 'error');
  }
};

const submitGeneration = async () => {
  const prompt = promptInput.value.trim();
  if (!prompt) {
    setStatus('Prompt required.', false);
    promptInput.focus();
    return;
  }

  const size = Number(sizeSelect.value) || 512;
  const payload = {
    prompt,
    negative_prompt: negativeInput.value.trim() || undefined,
    num_inference_steps: Number(stepsInput.value),
    guidance_scale: Number(guidanceInput.value),
    width: size,
    height: size,
    seed: seedInput.value === '' ? undefined : Number(seedInput.value)
  };

  setFormBusy(true);
  setStatus('Submitting render…');
  addLog(`→ Prompt: "${prompt.slice(0, 64)}${prompt.length > 64 ? '…' : ''}"`);

  try {
    const data = await fetchJson('/generate', {
      method: 'POST',
      body: JSON.stringify(payload)
    });
    setFormBusy(false);
    setStatus('Render complete.', true);
    setPreview(data.image_base64);
    setRawOutput(data);
    renderMeta(data);
    lastDurationEl.textContent = formatDuration(data.duration_ms);
    addLog(`✔ Render finished in ${formatDuration(data.duration_ms)}`, 'success');
  } catch (error) {
    setFormBusy(false);
    setStatus(`Render failed: ${error.message}`, false);
    addLog(`✖ Render failed: ${error.message}`, 'error');
    if (error.payload) {
      setRawOutput(error.payload);
    }
  }
};

const init = () => {
  if (stepsInput) {
    stepsInput.addEventListener('input', updateStepsLabel);
    updateStepsLabel();
  }
  if (guidanceInput) {
    guidanceInput.addEventListener('input', updateGuidanceLabel);
    updateGuidanceLabel();
  }
  if (healthRefreshBtn) {
    healthRefreshBtn.addEventListener('click', runHealthCheck);
  }
  if (clearLogsBtn) {
    clearLogsBtn.addEventListener('click', () => {
      if (logList) logList.innerHTML = '';
    });
  }
  if (form) {
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      submitGeneration();
    });
  }
  runHealthCheck().catch(() => {});
  setStatus('Ready to render.', true);
};

init();
