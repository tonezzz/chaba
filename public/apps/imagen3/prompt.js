import { appendIfMissing } from './utils.js';

const QUALITY_TAGS = 'masterpiece, best quality, highly detailed, sharp focus';
const NEGATIVE_PRESETS = 'worst quality, bad anatomy, deformed, extra limbs, missing fingers, mutated hands, watermark, signature, text, logo';

export function appendQualityTags(prompt) {
  return appendIfMissing(prompt, QUALITY_TAGS);
}

export function appendNegativePresets(negative) {
  return appendIfMissing(negative, NEGATIVE_PRESETS);
}

export function applyPromptPrefix(prompt, prefix) {
  if (!prefix) return prompt;
  const trimmed = (prompt || '').trim();
  if (!trimmed) return prefix.trim();
  return (prefix + trimmed).trim();
}
