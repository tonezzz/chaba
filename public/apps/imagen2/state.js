import { $ } from './utils.js';

export const MAX_HISTORY = 12;
export const MAX_QUEUE = 5;

export const state = {
  history: [],
  queue: [],
  activeJob: null,
  currentB64: null,
  refBase64: '',
  activeView: 'generated',
  pendingDeleteIndex: -1,
};

export function saveForm() {
  const form = {
    prompt: $('prompt').value,
    negative_prompt: $('negative').value,
    width: $('width').value,
    height: $('height').value,
    steps: $('steps').value,
    seed: $('seed').value,
    strength: $('strength').value,
    guidance_scale: $('guidance-scale').value,
    guidance_rescale: $('guidance-rescale').value
  };
  try { localStorage.setItem('imagen2_form', JSON.stringify(form)); } catch {}
}
