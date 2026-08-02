import { $ } from './utils.js';
import { state } from './state.js';
import { updateRefPreview } from './viewer.js';
import { getPreset } from './presets.js';

export const STORAGE_KEY = 'imagen3_form';

const QUALITY_TAGS = 'masterpiece, best quality, highly detailed, photorealistic, sharp focus';
const NEGATIVE_TAGS = 'worst quality, bad anatomy, deformed, extra limbs, missing fingers, mutated hands, watermark, signature, text, logo';

function appendMissingTags(text, tags) {
  const lowered = (text || '').toLowerCase();
  const missing = tags.split(',').map(s => s.trim()).filter(tag => !lowered.includes(tag));
  if (missing.length === 0) return text || '';
  const suffix = missing.join(', ');
  return (text ? text.trim().replace(/,+$/, '') + ', ' : '') + suffix;
}

export function readForm() {
  return {
    prompt: ($('prompt')?.value || '').trim(),
    negative_prompt: $('negative')?.value || '',
    width: parseInt($('width')?.value || 1024, 10),
    height: parseInt($('height')?.value || 1024, 10),
    steps: parseInt($('steps')?.value || 25, 10),
    seed: parseInt($('seed')?.value || -1, 10),
    strength: parseFloat($('strength')?.value || 0.5),
    guidance_scale: parseFloat($('guidance-scale')?.value || 7.5),
    guidance_rescale: parseFloat($('guidance-rescale')?.value || 0.7),
    mode: $('mode')?.value || 'lightning_txt2img'
  };
}

export function writeForm(values) {
  if ($('prompt') && values.prompt !== undefined) $('prompt').value = values.prompt;
  if ($('negative') && values.negative_prompt !== undefined) $('negative').value = values.negative_prompt;
  if ($('width') && values.width !== undefined) $('width').value = values.width;
  if ($('height') && values.height !== undefined) $('height').value = values.height;
  if ($('steps') && values.steps !== undefined) $('steps').value = values.steps;
  if ($('seed') && values.seed !== undefined) $('seed').value = values.seed;
  if ($('strength') && values.strength !== undefined) $('strength').value = values.strength;
  if ($('guidance-scale') && values.guidance_scale !== undefined) $('guidance-scale').value = values.guidance_scale;
  if ($('guidance-rescale') && values.guidance_rescale !== undefined) $('guidance-rescale').value = values.guidance_rescale;
  if ($('mode') && values.mode !== undefined) $('mode').value = values.mode;
  syncSize();
}

export function saveForm() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(readForm()));
  } catch {}
}

export function loadForm() {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    writeForm(stored);
  } catch {}
}

export function getGenerationBody(refBase64, values = null) {
  const f = values || readForm();
  let prompt = appendMissingTags(f.prompt, QUALITY_TAGS);
  const prefix = state.currentPreset ? (getPreset(state.currentPreset)?.prompt_prefix || '') : '';
  if (prefix && !prompt.toLowerCase().startsWith(prefix.toLowerCase())) {
    prompt = prefix + prompt;
  }
  const body = {
    prompt,
    negative_prompt: appendMissingTags(f.negative_prompt, NEGATIVE_TAGS),
    width: f.width,
    height: f.height,
    steps: f.steps,
    seed: f.seed,
    strength: f.strength,
    guidance_scale: f.guidance_scale,
    guidance_rescale: f.guidance_rescale,
    mode: f.mode
  };
  if (refBase64 && f.mode.includes('img2img')) {
    body.image = refBase64.split(',')[1] || refBase64;
  }
  if (body.image && body.steps * body.strength < 1) {
    throw new Error('For image-to-image, steps × strength must be at least 1');
  }
  return body;
}

export function recallItem(item) {
  const mode = item.mode || (item.image ? 'fast_img2img' : 'lightning_txt2img');
  writeForm({ ...item, mode });
  state.refBase64 = item.image || '';
  updateRefPreview();
  saveForm();
  try { localStorage.setItem('imagen3_ref', state.refBase64 || ''); } catch {}
}

export function syncSize() {
  const sizeEl = $('size');
  if (!sizeEl || !$('width') || !$('height')) return;
  const key = `${$('width').value}x${$('height').value}`;
  const option = [...sizeEl.options].find(o => o.value === key);
  sizeEl.value = option ? key : '';
}

export function setAdvancedVisible(visible) {
  const adv = $('advanced');
  if (adv) adv.open = visible;
}
