import { $ } from './utils.js';
import { state } from './state.js';
import { PRESETS, getPreset } from './presets.js';
import { loadForm, writeForm, saveForm, syncSize, setAdvancedVisible, getGenerationBody } from './params.js';
import { readFile } from './utils.js';
import { appendQualityTags, appendNegativePresets } from './prompt.js';
import { generate, regenerateLast, enqueue } from './generation.js';
import { renderHistory, closeModal } from './history.js';
import { renderViewer, updateRefPreview, updateGenerateBtn, statusEl } from './viewer.js';
import { checkHealth, loadHistory } from './api.js';

state.presets = PRESETS;

function applyPreset(name) {
  const p = getPreset(name);
  if (!p) {
    state.currentPreset = '';
    const hint = $('preset-hint');
    if (hint) hint.textContent = '';
    return;
  }
  state.currentPreset = name;
  const mode = p.mode === 'txt2img' ? 'lightning_txt2img' : 'fast_img2img';
  writeForm({ ...p.params, mode });
  const hint = $('preset-hint');
  if (hint) {
    hint.textContent = p.description + (p.prompt_prefix ? ` Prefix: "${p.prompt_prefix.trim()}"` : '');
  }
  const refField = $('ref-field');
  const strengthField = $('strength-field');
  if (refField) refField.style.display = p.mode === 'txt2img' ? 'none' : 'block';
  if (strengthField) strengthField.style.display = p.mode === 'txt2img' ? 'none' : 'block';
  if (p.mode === 'txt2img' && state.refBase64) {
    state.refBase64 = '';
    updateRefPreview();
  }
  saveForm();
}

function populatePresets() {
  const select = $('preset');
  if (!select) return;
  select.innerHTML = '<option value="" selected>Custom</option>';
  const txt = document.createElement('optgroup');
  txt.label = 'txt2img';
  const img = document.createElement('optgroup');
  img.label = 'img2img';
  PRESETS.forEach(p => {
    const opt = document.createElement('option');
    opt.value = p.name;
    opt.textContent = p.name;
    if (p.mode === 'txt2img') txt.appendChild(opt);
    else img.appendChild(opt);
  });
  select.appendChild(txt);
  select.appendChild(img);
}

function wireEvents() {
  if ($('generate')) $('generate').addEventListener('click', generate);
  if ($('regenerate')) $('regenerate').addEventListener('click', () => regenerateLast(false));
  if ($('variate')) $('variate').addEventListener('click', () => regenerateLast(true));
  if ($('preset')) $('preset').addEventListener('change', (e) => { applyPreset(e.target.value); });
  if ($('add-quality')) $('add-quality').addEventListener('click', () => {
    $('prompt').value = appendQualityTags($('prompt').value);
    saveForm();
  });
  if ($('add-negative')) $('add-negative').addEventListener('click', () => {
    $('negative').value = appendNegativePresets($('negative').value);
    saveForm();
  });
  if ($('reference')) $('reference').addEventListener('change', async () => {
    const file = $('reference').files[0];
    if (!file) return;
    try {
      state.refBase64 = await readFile(file);
      if ($('mode').value === 'lightning_txt2img') $('mode').value = 'fast_img2img';
      updateRefPreview();
      saveForm();
    } catch (e) {
      if (statusEl) {
        statusEl.textContent = `Failed to read reference: ${e.message}`;
        statusEl.className = 'status error';
      }
    }
  });
  if ($('ref-clear')) $('ref-clear').addEventListener('click', () => {
    $('reference').value = '';
    state.refBase64 = '';
    if ($('mode').value !== 'lightning_txt2img') $('mode').value = 'lightning_txt2img';
    updateRefPreview();
    try { localStorage.removeItem('imagen3_ref'); } catch {}
    saveForm();
  });
  ['prompt', 'negative', 'width', 'height', 'steps', 'seed', 'guidance-scale', 'guidance-rescale', 'strength', 'mode'].forEach(id => {
    const el = $(id);
    if (el) el.addEventListener('change', saveForm);
  });
  if ($('size')) $('size').addEventListener('change', () => {
    const [w, h] = $('size').value.split('x');
    if ($('width')) $('width').value = w;
    if ($('height')) $('height').value = h;
    syncSize();
    saveForm();
  });
  document.querySelectorAll('.size-chips .chip').forEach(chip => {
    chip.addEventListener('click', () => {
      if ($('size')) $('size').value = chip.dataset.size;
      $('size').dispatchEvent(new Event('change'));
    });
  });
  if ($('view-tabs')) $('view-tabs').addEventListener('click', (e) => {
    if (e.target.tagName !== 'BUTTON') return;
    state.activeView = e.target.dataset.tab || 'generated';
    renderViewer();
  });
  if ($('modal-close')) $('modal-close').addEventListener('click', closeModal);
  if ($('modal-generate')) $('modal-generate').addEventListener('click', async () => {
    const file = $('modal-ref')?.files?.[0];
    let ref = '';
    if (file) {
      try { ref = await readFile(file); } catch (e) { alert(`Failed to read reference: ${e.message}`); return; }
    }
    const values = {
      prompt: ($('modal-prompt')?.value || '').trim(),
      negative_prompt: $('modal-negative')?.value || '',
      mode: $('modal-mode')?.value || 'lightning_txt2img',
      width: parseInt($('modal-width')?.value || 1024, 10),
      height: parseInt($('modal-height')?.value || 1024, 10),
      steps: parseInt($('modal-steps')?.value || 25, 10),
      seed: parseInt($('modal-seed')?.value || -1, 10),
      strength: parseFloat($('modal-strength')?.value || 0.5),
      guidance_scale: parseFloat($('modal-guidance-scale')?.value || 7.5),
      guidance_rescale: parseFloat($('modal-guidance-rescale')?.value || 0.7)
    };
    if (values.mode.includes('img2img') && !ref) { alert('Reference image required for img2img modes'); return; }
    let body;
    try { body = getGenerationBody(ref, values); } catch (e) { alert(e.message); return; }
    enqueue(body, ref);
    closeModal();
  });
}

async function boot() {
  populatePresets();
  loadForm();
  const ref = localStorage.getItem('imagen3_ref');
  if (ref) state.refBase64 = ref;
  updateRefPreview();
  state.history = await loadHistory();
  renderHistory();
  updateGenerateBtn();
  try {
    const data = await checkHealth();
    if (statusEl) {
      statusEl.textContent = `Backend ready: ${data.model}`;
      statusEl.className = 'status ok';
    }
  } catch (e) {
    if (statusEl) {
      statusEl.textContent = `Backend unavailable (${e.message})`;
      statusEl.className = 'status error';
    }
  }
  wireEvents();
  setAdvancedVisible(false);
}

boot();
