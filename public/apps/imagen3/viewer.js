import { $ } from './utils.js';
import { state } from './state.js';
import { imageUrl } from './api.js';

export const statusEl = $('status');
export const generateBtn = $('generate');
export const outputEl = $('output');
export const thumbsEl = $('thumbs');
export const metaEl = $('meta');
export const progressEl = $('progress');
export const refPreview = $('ref-preview');
export const strengthVal = $('strength-val');

export function renderViewer() {
  if (!outputEl) return;
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
  if (state.currentItem && state.currentItem.image_url) {
    outputEl.innerHTML = `<img src="${imageUrl(state.currentItem.image_url)}" alt="Generated">`;
    return;
  }
  outputEl.innerHTML = '<div class="placeholder"><div class="placeholder-title">Ready to generate</div><div class="placeholder-hint">Pick a preset, enter a prompt, then click Generate.</div></div>';
}

export function updateGenerateBtn() {
  if (!generateBtn) return;
  const pendingCount = state.history.filter(i => i.pending).length;
  if (pendingCount >= state.MAX_QUEUE) {
    generateBtn.disabled = true;
    generateBtn.textContent = 'Queue full';
  } else {
    generateBtn.disabled = false;
    generateBtn.textContent = state.activeJob ? 'Add to queue' : 'Generate';
  }
}

export function updateRefPreview() {
  if (refPreview) {
    refPreview.src = state.refBase64 || '';
    refPreview.classList.toggle('visible', !!state.refBase64);
  }
  renderTabs();
  renderViewer();
}

export function renderTabs() {
  const tabs = $('view-tabs');
  if (!tabs) return;
  tabs.style.display = state.refBase64 ? 'flex' : 'none';
  tabs.querySelectorAll('button').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === state.activeView);
  });
}

export function updateMeta(item) {
  if (!metaEl || !item) return;
  const seedSuffix = (item.requested_seed !== undefined && item.requested_seed < 0) ? ' (random)' : '';
  metaEl.textContent = `${item.width}x${item.height} · steps ${item.steps} · seed ${item.seed}${seedSuffix} · ${item.time || 0}s`;
}
