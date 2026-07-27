import { $ } from './utils.js';
import { state, saveForm, MAX_HISTORY, MAX_QUEUE } from './state.js';
import { saveHistory } from './api.js';

export const statusEl = $('status');
export const generateBtn = $('generate');
export const outputEl = $('output');
export const thumbsEl = $('thumbs');
export const metaEl = $('meta');
export const downloadSelect = $('download-scale');
export const progressEl = $('progress');
export const refInput = $('reference');
export const refPreview = $('ref-preview');
export const refClear = $('ref-clear');
export const strengthEl = $('strength');
export const strengthVal = $('strength-val');

export function updateRefPreview() {
  refPreview.src = state.refBase64;
  refPreview.classList.toggle('visible', !!state.refBase64);
  renderTabs();
  if (state.activeView === 'original') renderViewer();
}

export function renderTabs() {
  const tabs = $('view-tabs');
  if (!tabs) return;
  const hasRef = !!state.refBase64;
  tabs.style.display = hasRef ? 'flex' : 'none';
  tabs.querySelectorAll('button').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === state.activeView);
  });
}

export function renderViewer() {
  if (state.activeView === 'original' && state.refBase64) {
    outputEl.innerHTML = `<img src="${state.refBase64}" alt="Original">`;
    return;
  }
  if (state.activeJob && state.activeJob.preview) {
    outputEl.innerHTML = `<img src="${state.activeJob.preview}" alt="Preview" style="max-width:100%;max-height:70vh">`;
    return;
  }
  if (state.activeJob) {
    outputEl.innerHTML = '<div class="placeholder"><div class="spinner"></div>Generating image...</div>';
    return;
  }
  if (state.currentB64) {
    outputEl.innerHTML = `<img src="data:image/png;base64,${state.currentB64}" alt="Generated">`;
    return;
  }
  outputEl.innerHTML = '<div class="placeholder">Generated image will appear here</div>';
}

export function updateGenerateBtn() {
  const pendingCount = state.history.filter(i => i.pending).length;
  if (pendingCount >= MAX_QUEUE) {
    generateBtn.disabled = true;
    generateBtn.textContent = 'Queue full';
  } else {
    generateBtn.disabled = false;
    generateBtn.textContent = state.activeJob ? 'Add to queue' : 'Generate';
  }
}

export function restoreState() {
  try {
    const form = JSON.parse(localStorage.getItem('imagen2_form') || '{}');
    if (form.prompt !== undefined) $('prompt').value = form.prompt;
    if (form.negative_prompt !== undefined) $('negative').value = form.negative_prompt;
    if (form.width !== undefined) $('width').value = form.width;
    if (form.height !== undefined) $('height').value = form.height;
    if (form.steps !== undefined) $('steps').value = form.steps;
    if (form.seed !== undefined) $('seed').value = form.seed;
    if (form.strength !== undefined) {
      $('strength').value = form.strength;
      strengthVal.textContent = form.strength;
    }
    if (form.guidance_scale !== undefined) {
      $('guidance-scale').value = form.guidance_scale;
    }
    if (form.guidance_rescale !== undefined) {
      $('guidance-rescale').value = form.guidance_rescale;
    }
  } catch {}
  try {
    const ref = localStorage.getItem('imagen2_ref');
    if (ref) { state.refBase64 = ref; updateRefPreview(); }
  } catch {}
  try {
    const last = JSON.parse(localStorage.getItem('imagen2_last') || '{}');
    if (last && last.b64) { showImage(last); }
  } catch {}
}

export function renderHistory() {
  thumbsEl.innerHTML = '';
  state.history.forEach((item, i) => {
    const div = document.createElement('div');
    const isActive = item === state.activeJob || (!state.activeJob && item.b64 === state.currentB64);
    div.className = 'thumb' + (isActive ? ' active' : '') + (item.pending ? ' pending' : '');
    const img = document.createElement('img');
    if (item.pending && item.preview) {
      img.src = item.preview;
    } else if (item.pending) {
      img.style.display = 'none';
    } else {
      img.src = `data:image/png;base64,${item.b64}`;
    }
    img.alt = item.prompt || '';
    div.appendChild(img);
    if (item.pending) {
      const overlay = document.createElement('div');
      overlay.className = 'overlay';
      if (item.error) {
        div.classList.add('error');
        const label = document.createElement('div');
        label.className = 'step-label';
        label.textContent = 'Error';
        overlay.appendChild(label);
      } else if (!item.submitted) {
        const pos = state.queue.indexOf(item) + 1;
        const qLabel = document.createElement('div');
        qLabel.className = 'queued-label';
        qLabel.textContent = `Queued #${pos}`;
        div.appendChild(qLabel);
      } else {
        const stepLabel = document.createElement('div');
        stepLabel.className = 'step-label';
        stepLabel.textContent = item.progress ? `Step ${item.progress.step}/${item.totalSteps}` : 'Starting...';
        overlay.appendChild(stepLabel);
        const pbar = document.createElement('div');
        pbar.className = 'progress-bar';
        const fill = document.createElement('div');
        const pct = item.progress && item.totalSteps ? Math.min(100, Math.round((item.progress.step / item.totalSteps) * 100)) : 0;
        fill.style.width = `${pct}%`;
        pbar.appendChild(fill);
        overlay.appendChild(pbar);
      }
      div.appendChild(overlay);
    }
    const removeBtn = document.createElement('button');
    removeBtn.className = 'remove';
    removeBtn.textContent = '×';
    removeBtn.title = 'Remove';
    removeBtn.onclick = (e) => {
      e.stopPropagation();
      if (state.pendingDeleteIndex === i) {
        removeHistory(i);
      } else {
        resetDeleteButtons();
        removeBtn.textContent = 'Y';
        removeBtn.classList.add('confirm');
        state.pendingDeleteIndex = i;
      }
    };
    div.appendChild(removeBtn);
    div.onclick = () => recallItem(item);
    thumbsEl.appendChild(div);
  });
  const hasCompleted = state.history.some(i => !i.pending);
  const regenerateBtn = $('regenerate');
  const variateBtn = $('variate');
  if (regenerateBtn) regenerateBtn.disabled = !hasCompleted;
  if (variateBtn) variateBtn.disabled = !hasCompleted;
}

export function removeHistory(idx) {
  state.pendingDeleteIndex = -1;
  const item = state.history[idx];
  if (item && item.pending) {
    if (item === state.activeJob) {
      item.discarded = true;
    } else {
      state.queue = state.queue.filter(q => q !== item);
    }
  }
  state.history.splice(idx, 1);
  renderHistory();
  saveHistory(state.history, MAX_HISTORY);
  updateGenerateBtn();
}

export function resetDeleteButtons() {
  document.querySelectorAll('.remove').forEach(btn => {
    btn.textContent = '×';
    btn.classList.remove('confirm');
  });
  state.pendingDeleteIndex = -1;
}

export function recallItem(item) {
  resetDeleteButtons();
  $('prompt').value = item.prompt || '';
  $('negative').value = item.negative_prompt || '';
  $('width').value = item.width || 1024;
  $('height').value = item.height || 1024;
  $('steps').value = item.steps || 25;
  const wasRandom = item.requested_seed !== undefined && item.requested_seed < 0;
  $('seed').value = wasRandom ? -1 : (item.seed !== undefined ? item.seed : -1);
  $('strength').value = item.strength !== undefined ? item.strength : 0.5;
  strengthVal.textContent = $('strength').value;
  $('guidance-scale').value = item.guidance_scale !== undefined ? item.guidance_scale : 7.5;
  $('guidance-rescale').value = item.guidance_rescale !== undefined ? item.guidance_rescale : 0.7;
  state.refBase64 = item.image || '';
  state.activeView = 'generated';
  updateRefPreview();
  saveForm();
  try { localStorage.setItem('imagen2_ref', state.refBase64 || ''); } catch {}
  if (state.activeJob) {
    renderViewer();
  } else {
    showImage(item);
  }
}

export function showImage(item) {
  state.currentB64 = item.b64;
  renderViewer();
  const seedSuffix = item.requested_seed < 0 ? ' (random)' : '';
  metaEl.textContent = `${item.width}x${item.height} · steps ${item.steps} · seed ${item.seed}${seedSuffix} · ${item.time}s`;
  downloadSelect.disabled = false;
  renderHistory();
  try { localStorage.setItem('imagen2_last', JSON.stringify(item)); } catch {}
}
