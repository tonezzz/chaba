import { $ } from './utils.js';
import { state } from './state.js';
import { imageUrl, deleteHistory } from './api.js';
import { renderViewer, updateGenerateBtn } from './viewer.js';

export function renderHistory() {
  const thumbsEl = $('thumbs');
  if (!thumbsEl) return;
  thumbsEl.innerHTML = '';
  state.history.forEach((item, i) => {
    const div = document.createElement('div');
    const isActive = item === state.activeJob || (!state.activeJob && item === state.currentItem);
    div.className = 'thumb' + (isActive ? ' active' : '') + (item.pending ? ' pending' : '');
    const img = document.createElement('img');
    if (item.pending && item.preview) {
      img.src = item.preview;
    } else if (item.pending) {
      img.style.display = 'none';
    } else {
      img.src = imageUrl(item.thumb_url || item.image_url);
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
        removeHistoryItem(i);
      } else {
        resetDeleteButtons();
        removeBtn.textContent = 'Y';
        removeBtn.classList.add('confirm');
        state.pendingDeleteIndex = i;
      }
    };
    div.appendChild(removeBtn);
    div.onclick = () => { if (!item.pending) openModal(item); };
    thumbsEl.appendChild(div);
  });
  const hasCompleted = state.history.some(i => !i.pending);
  const regen = $('regenerate');
  const variate = $('variate');
  if (regen) regen.disabled = !hasCompleted;
  if (variate) variate.disabled = !hasCompleted;
}

export function removeHistoryItem(idx) {
  state.pendingDeleteIndex = -1;
  const item = state.history[idx];
  if (item && item.pending) {
    if (item === state.activeJob) {
      item.discarded = true;
    } else {
      state.queue = state.queue.filter(q => q !== item);
    }
  }
  if (item && item.id) {
    deleteHistory(item.id).catch(e => console.error('Failed to delete history item:', e));
  }
  state.history.splice(idx, 1);
  renderHistory();
  updateGenerateBtn();
}

export function resetDeleteButtons() {
  document.querySelectorAll('.remove').forEach(btn => {
    btn.textContent = '×';
    btn.classList.remove('confirm');
  });
  state.pendingDeleteIndex = -1;
}

function resizeNow(el) {
  if (!el) return;
  el.style.height = 'auto';
  el.style.height = el.scrollHeight + 'px';
}

function setupAutoResize(el, value) {
  if (!el) return;
  el.value = value;
  el.oninput = () => resizeNow(el);
  resizeNow(el);
}

export function openModal(item) {
  state.modalItem = item;
  state.currentItem = item;
  renderHistory();
  const modal = $('history-modal');
  if (modal) modal.classList.remove('hidden');

  if ($('modal-img')) $('modal-img').src = item.image_url ? imageUrl(item.image_url) : '';

  const originalImg = $('modal-original-img');
  const originalEmpty = $('modal-original-empty');
  if (originalImg) {
    if (item.image) {
      originalImg.src = item.image;
      originalImg.style.display = 'block';
      if (originalEmpty) originalEmpty.style.display = 'none';
    } else {
      originalImg.style.display = 'none';
      if (originalEmpty) originalEmpty.style.display = 'block';
    }
  }

  const mode = item.mode || 'lightning_txt2img';
  setupAutoResize($('modal-prompt'), item.prompt || '');
  setupAutoResize($('modal-negative'), item.negative_prompt || '');
  if ($('modal-mode')) {
    $('modal-mode').value = mode;
    $('modal-mode').onchange = updateModalMode;
  }
  if ($('modal-width')) $('modal-width').value = String(item.width || 1024);
  if ($('modal-height')) $('modal-height').value = String(item.height || 1024);
  if ($('modal-steps')) $('modal-steps').value = String(item.steps || 25);
  if ($('modal-seed')) $('modal-seed').value = String(item.requested_seed !== undefined ? item.requested_seed : (item.seed !== undefined ? item.seed : -1));
  if ($('modal-guidance-scale')) $('modal-guidance-scale').value = String(item.guidance_scale || 7.5);
  if ($('modal-guidance-rescale')) $('modal-guidance-rescale').value = String(item.guidance_rescale !== undefined ? item.guidance_rescale : 0.7);
  if ($('modal-strength')) {
    $('modal-strength').value = String(item.strength !== undefined ? item.strength : 0.5);
    $('modal-strength').oninput = updateModalStrengthLabel;
  }
  updateModalStrengthLabel();
  if ($('modal-ref')) $('modal-ref').value = '';
  updateModalMode();

  document.querySelectorAll('.modal-tabs button').forEach(btn => {
    btn.onclick = () => switchModalTab(btn.dataset.modalTab);
  });
  switchModalTab('generated');
}

function updateModalMode() {
  const mode = $('modal-mode')?.value || 'lightning_txt2img';
  const isImg2Img = mode.includes('img2img');
  if ($('modal-strength-field')) $('modal-strength-field').style.display = isImg2Img ? 'block' : 'none';
  if ($('modal-ref-field')) $('modal-ref-field').style.display = isImg2Img ? 'block' : 'none';
}

function updateModalStrengthLabel() {
  const strength = $('modal-strength')?.value;
  if (strength && $('modal-strength-val')) $('modal-strength-val').textContent = strength;
}

function switchModalTab(name) {
  document.querySelectorAll('.modal-tabs button').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.modalTab === name);
  });
  document.querySelectorAll('.modal-panel').forEach(panel => {
    panel.classList.toggle('active', panel.id === `modal-${name}`);
  });
  if (name === 'parameters') {
    resizeNow($('modal-prompt'));
    resizeNow($('modal-negative'));
  }
}

export function closeModal() {
  state.modalItem = null;
  const modal = $('history-modal');
  if (modal) modal.classList.add('hidden');
}
