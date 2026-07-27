import { $, readFile, base64ToBlob, appendIfMissing } from './utils.js';
import { state, saveForm, MAX_QUEUE } from './state.js';
import * as api from './api.js';
import * as ui from './ui.js';

export function downloadScale(scale) {
  if (!state.currentB64) return;
  ui.downloadSelect.disabled = true;
  api.downloadUpscaled(state.currentB64, scale)
    .then(data => {
      const mime = `image/${data.format.toLowerCase()}`;
      const blob = base64ToBlob(data.image_base64, mime);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `imagen_${data.width}x${data.height}_${scale}x.${data.format.toLowerCase()}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    })
    .catch(e => {
      const msg = typeof e === 'string' ? e : (e && e.message ? e.message : String(e));
      ui.statusEl.textContent = `Upscale error: ${msg}`;
      ui.statusEl.className = 'status error';
    })
    .finally(() => {
      ui.downloadSelect.disabled = false;
      ui.downloadSelect.value = '';
    });
}

export function regenerateLast(newSeed = false) {
  const item = state.history.find(i => !i.pending);
  if (!item) {
    alert('No completed history item');
    return;
  }
  ui.recallItem(item);
  if (newSeed) $('seed').value = -1;
  generate();
}

export function finishGenerate(queueItem, data) {
  state.activeJob = null;
  if (!queueItem.discarded) {
    const item = {
      b64: data.image_base64,
      prompt: queueItem.body.prompt,
      negative_prompt: queueItem.body.negative_prompt,
      width: queueItem.body.width,
      height: queueItem.body.height,
      steps: queueItem.body.steps,
      seed: data.seed,
      requested_seed: queueItem.body.seed,
      strength: queueItem.body.strength,
      guidance_scale: queueItem.body.guidance_scale,
      guidance_rescale: queueItem.body.guidance_rescale,
      image: queueItem.ref,
      time: data.inference_time
    };
    const idx = state.history.indexOf(queueItem);
    if (idx !== -1) state.history[idx] = item;
    else state.history.unshift(item);
    state.currentB64 = item.b64;
    ui.showImage(item);
    ui.statusEl.textContent = 'Done';
    ui.statusEl.className = 'status ok';
    api.saveHistory(state.history);
  }
  ui.updateGenerateBtn();
  processNext();
}

export function poll(queueItem) {
  api.fetchProgress(queueItem.job_id)
    .then(data => {
      if (data === null) {
        queueItem.timer = setTimeout(() => poll(queueItem), 500);
        return;
      }
      if (data.error) throw new Error(data.error);
      if (data.done) {
        finishGenerate(queueItem, data.result);
        return;
      }
      if (data.progress && data.progress.image) {
        queueItem.preview = `data:image/jpeg;base64,${data.progress.image}`;
        queueItem.progress = { step: data.progress.step };
        ui.renderHistory();
        if (queueItem === state.activeJob) {
          ui.renderViewer();
          ui.metaEl.textContent = `Step ${data.progress.step}/${queueItem.totalSteps}`;
          ui.progressEl.value = Math.min(data.progress.step, queueItem.totalSteps);
          ui.progressEl.max = queueItem.totalSteps || 100;
          ui.progressEl.style.display = 'block';
        }
      }
      queueItem.timer = setTimeout(() => poll(queueItem), 500);
    })
    .catch(e => {
      const msg = typeof e === 'string' ? e : (e && e.message ? e.message : String(e));
      queueItem.error = msg;
      if (queueItem === state.activeJob) {
        state.activeJob = null;
        ui.statusEl.textContent = `Error: ${msg}`;
        ui.statusEl.className = 'status error';
        ui.progressEl.style.display = 'none';
      }
      ui.renderHistory();
      ui.updateGenerateBtn();
      processNext();
    });
}

export async function generate() {
  saveForm();
  const prompt = $('prompt').value.trim();
  if (!prompt) {
    alert('Please enter a prompt');
    return;
  }
  if (state.history.filter(i => i.pending).length >= MAX_QUEUE) {
    alert('Queue is full');
    return;
  }
  const body = {
    prompt,
    negative_prompt: $('negative').value,
    width: parseInt($('width').value, 10),
    height: parseInt($('height').value, 10),
    steps: parseInt($('steps').value, 10),
    seed: parseInt($('seed').value, 10),
    strength: parseFloat($('strength').value),
    guidance_scale: parseFloat($('guidance-scale').value),
    guidance_rescale: parseFloat($('guidance-rescale').value)
  };
  const ref = state.refBase64;
  if (ref) {
    body.image = ref.split(',')[1] || ref;
  }
  if (body.image && body.steps * body.strength < 1) {
    ui.statusEl.textContent = 'Error: for image-to-image, steps × strength must be at least 1';
    ui.statusEl.className = 'status error';
    return;
  }
  const totalSteps = body.image
    ? Math.max(1, Math.floor(body.steps * body.strength))
    : body.steps;
  const queueItem = {
    pending: true,
    submitted: false,
    discarded: false,
    body,
    ref,
    totalSteps,
    prompt: body.prompt,
    negative_prompt: body.negative_prompt,
    width: body.width,
    height: body.height,
    steps: body.steps,
    seed: body.seed,
    strength: body.strength,
    guidance_scale: body.guidance_scale,
    guidance_rescale: body.guidance_rescale,
    time: 0,
    progress: null,
    preview: null,
    error: null,
    job_id: null,
    timer: null
  };
  state.history.unshift(queueItem);
  state.queue.push(queueItem);
  state.activeView = 'generated';
  ui.renderTabs();
  ui.renderHistory();
  ui.updateGenerateBtn();
  if (!state.activeJob) {
    processNext();
  }
}

export function processNext() {
  if (state.activeJob) return;
  if (state.queue.length === 0) {
    ui.updateGenerateBtn();
    ui.statusEl.textContent = 'Ready';
    ui.statusEl.className = 'status ok';
    ui.progressEl.style.display = 'none';
    return;
  }
  const next = state.queue.shift();
  state.activeJob = next;
  ui.statusEl.textContent = 'Generating...';
  ui.statusEl.className = 'status';
  ui.progressEl.value = 0;
  ui.progressEl.max = next.totalSteps || 100;
  ui.progressEl.style.display = 'block';
  ui.updateGenerateBtn();
  ui.renderHistory();
  ui.renderViewer();
  startGenerate(next);
}

export async function startGenerate(queueItem) {
  queueItem.submitted = true;
  try {
    const data = await api.postGenerate(queueItem.body);
    queueItem.job_id = data.job_id;
    ui.renderHistory();
    ui.renderViewer();
    poll(queueItem);
  } catch (e) {
    const msg = typeof e === 'string' ? e : (e && e.message ? e.message : String(e));
    queueItem.error = msg;
    if (queueItem === state.activeJob) {
      state.activeJob = null;
      ui.statusEl.textContent = `Error: ${msg}`;
      ui.statusEl.className = 'status error';
      ui.progressEl.style.display = 'none';
    }
    ui.renderHistory();
    ui.updateGenerateBtn();
    processNext();
  }
}

// Event wiring
ui.generateBtn.addEventListener('click', generate);

document.addEventListener('click', () => {
  if (state.pendingDeleteIndex !== -1) ui.resetDeleteButtons();
});

$('add-quality').addEventListener('click', () => {
  appendIfMissing($('prompt'), 'masterpiece, best quality, highly detailed, sharp focus');
  saveForm();
});

$('add-negative').addEventListener('click', () => {
  appendIfMissing($('negative'), 'worst quality, bad anatomy, deformed, extra limbs, missing fingers, mutated hands, watermark, signature, text, logo');
  saveForm();
});

$('regenerate').addEventListener('click', () => regenerateLast(false));
$('variate').addEventListener('click', () => regenerateLast(true));

['prompt', 'negative', 'width', 'height', 'steps', 'seed', 'guidance-scale', 'guidance-rescale'].forEach(id => {
  const el = $(id);
  if (el) el.addEventListener('change', saveForm);
});
ui.strengthEl.addEventListener('input', saveForm);

ui.refInput.addEventListener('change', async () => {
  const file = ui.refInput.files[0];
  if (!file) {
    state.refBase64 = '';
    ui.updateRefPreview();
    try { localStorage.removeItem('imagen2_ref'); } catch {}
    return;
  }
  try {
    state.refBase64 = await readFile(file);
    ui.updateRefPreview();
    try { localStorage.setItem('imagen2_ref', state.refBase64); } catch {}
  } catch (e) {
    ui.statusEl.textContent = `Failed to read reference image: ${e.message}`;
    ui.statusEl.className = 'status error';
  }
});

ui.refClear.addEventListener('click', () => {
  ui.refInput.value = '';
  state.refBase64 = '';
  ui.updateRefPreview();
  try { localStorage.removeItem('imagen2_ref'); } catch {}
});

ui.strengthEl.addEventListener('input', () => {
  ui.strengthVal.textContent = ui.strengthEl.value;
});

$('view-tabs').addEventListener('click', (e) => {
  if (e.target.tagName !== 'BUTTON') return;
  state.activeView = e.target.dataset.tab || 'generated';
  ui.renderTabs();
  ui.renderViewer();
});

ui.downloadSelect.addEventListener('change', () => {
  const scale = ui.downloadSelect.value;
  if (!scale) return;
  downloadScale(scale);
});

(async () => {
  state.history = await api.loadHistory();
  ui.restoreState();
  try {
    const data = await api.checkHealth();
    ui.statusEl.textContent = `Backend ready: ${data.model}`;
    ui.statusEl.className = 'status ok';
    ui.updateGenerateBtn();
  } catch (e) {
    ui.statusEl.textContent = `Backend unavailable (${e.message})`;
    ui.statusEl.className = 'status error';
  }
})();
