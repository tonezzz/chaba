import { $ } from './utils.js';
import { state } from './state.js';
import { getGenerationBody, saveForm, recallItem } from './params.js';
import { appendQualityTags, appendNegativePresets, applyPromptPrefix } from './prompt.js';
import * as api from './api.js';
import { renderHistory, resetDeleteButtons } from './history.js';
import { renderViewer, updateGenerateBtn, statusEl, updateMeta } from './viewer.js';

export function enqueue(body, ref = '') {
  if (state.history.filter(i => i.pending).length >= state.MAX_QUEUE) {
    alert('Queue is full');
    return;
  }

  const totalSteps = body.mode.includes('img2img')
    ? Math.max(1, Math.floor(body.steps * body.strength))
    : body.steps;

  const queueItem = {
    pending: true,
    submitted: false,
    discarded: false,
    body,
    ref: ref || '',
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
    mode: body.mode,
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
  renderViewer();
  renderHistory();
  updateGenerateBtn();
  if (!state.activeJob) processNext();
}

export function generate() {
  saveForm();
  let prompt = ($('prompt')?.value || '').trim();
  if (!prompt) {
    alert('Please enter a prompt');
    return;
  }

  const negative = appendNegativePresets($('negative')?.value || '');
  const presetName = $('preset')?.value || '';
  const preset = state.presets.find(p => p.name === presetName) || null;
  if (preset && preset.prompt_prefix) {
    prompt = applyPromptPrefix(prompt, preset.prompt_prefix);
  }
  prompt = appendQualityTags(prompt);

  $('prompt').value = prompt;
  $('negative').value = negative;
  saveForm();

  let body;
  try {
    body = getGenerationBody(state.refBase64);
  } catch (e) {
    if (statusEl) {
      statusEl.textContent = `Error: ${e.message}`;
      statusEl.className = 'status error';
    }
    return;
  }

  enqueue(body, state.refBase64);
}

export function processNext() {
  if (state.activeJob) return;
  if (state.queue.length === 0) {
    updateGenerateBtn();
    if (statusEl) {
      statusEl.textContent = 'Ready';
      statusEl.className = 'status ok';
    }
    if ($('progress')) $('progress').style.display = 'none';
    return;
  }
  const next = state.queue.shift();
  state.activeJob = next;
  if (statusEl) {
    statusEl.textContent = 'Generating...';
    statusEl.className = 'status';
  }
  if ($('progress')) {
    $('progress').value = 0;
    $('progress').max = next.totalSteps || 100;
    $('progress').style.display = 'block';
  }
  updateGenerateBtn();
  renderHistory();
  renderViewer();
  startGenerate(next);
}

async function startGenerate(queueItem) {
  queueItem.submitted = true;
  try {
    const data = await api.postGenerate(queueItem.body);
    queueItem.job_id = data.job_id;
    renderHistory();
    renderViewer();
    poll(queueItem);
  } catch (e) {
    const msg = typeof e === 'string' ? e : (e && e.message ? e.message : String(e));
    queueItem.error = msg;
    if (queueItem === state.activeJob) {
      state.activeJob = null;
      if (statusEl) {
        statusEl.textContent = `Error: ${msg}`;
        statusEl.className = 'status error';
      }
      if ($('progress')) $('progress').style.display = 'none';
    }
    renderHistory();
    updateGenerateBtn();
    processNext();
  }
}

function poll(queueItem) {
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
        renderHistory();
        if (queueItem === state.activeJob) {
          renderViewer();
          if ($('meta')) $('meta').textContent = `Step ${data.progress.step}/${queueItem.totalSteps}`;
          if ($('progress')) {
            $('progress').value = Math.min(data.progress.step, queueItem.totalSteps);
            $('progress').max = queueItem.totalSteps || 100;
          }
        }
      }
      queueItem.timer = setTimeout(() => poll(queueItem), 500);
    })
    .catch(e => {
      const msg = typeof e === 'string' ? e : (e && e.message ? e.message : String(e));
      queueItem.error = msg;
      if (queueItem === state.activeJob) {
        state.activeJob = null;
        if (statusEl) {
          statusEl.textContent = `Error: ${msg}`;
          statusEl.className = 'status error';
        }
        if ($('progress')) $('progress').style.display = 'none';
      }
      renderHistory();
      updateGenerateBtn();
      processNext();
    });
}

function finishGenerate(queueItem, data) {
  state.activeJob = null;
  if (!queueItem.discarded) {
    const item = {
      id: data.id,
      image_url: data.image_url,
      thumb_url: data.thumb_url,
      image_base64: data.image_base64,
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
      mode: queueItem.body.mode,
      image: queueItem.ref,
      time: data.inference_time
    };
    const idx = state.history.indexOf(queueItem);
    if (idx !== -1) state.history[idx] = item;
    else state.history.unshift(item);
    state.currentItem = item;
    state.currentB64 = item.image_base64 || null;
    renderViewer();
    updateMeta(item);
    if (statusEl) {
      statusEl.textContent = 'Done';
      statusEl.className = 'status ok';
    }
    if ($('progress')) $('progress').style.display = 'none';
    try { localStorage.setItem('imagen3_last', JSON.stringify(item)); } catch {}
  }
  updateGenerateBtn();
  processNext();
}

export function regenerateLast(newSeed = false) {
  const item = state.history.find(i => !i.pending);
  if (!item) {
    alert('No completed history item');
    return;
  }
  recallItem(item);
  if (newSeed && $('seed')) $('seed').value = -1;
  generate();
}
