export const PRESETS = [
  {
    name: 'Quick',
    mode: 'txt2img',
    description: 'Quickly test an idea.',
    params: { width: 512, height: 512, steps: 4, guidance_scale: 1.0, guidance_rescale: 0.0, seed: -1 }
  },
  {
    name: 'Improve',
    mode: 'txt2img',
    description: 'Higher quality while still fast.',
    params: { width: 768, height: 768, steps: 4, guidance_scale: 1.0, guidance_rescale: 0.0, seed: -1 }
  },
  {
    name: 'Best',
    mode: 'txt2img',
    description: 'Best quality.',
    params: { width: 1024, height: 1024, steps: 4, guidance_scale: 1.0, guidance_rescale: 0.0, seed: -1 }
  },
  {
    name: 'ChangeClothes',
    mode: 'img2img',
    description: 'Change clothes, keep the rest.',
    prompt_prefix: 'change the clothes to ',
    params: { width: 1024, height: 1024, strength: 0.65, steps: 12, guidance_scale: 8.5, guidance_rescale: 0.7, seed: -1 }
  },
  {
    name: 'BlueSkyScene',
    mode: 'img2img',
    description: 'Change to a blue sky scene.',
    prompt_prefix: 'blue sky, clear sky, ',
    params: { width: 1024, height: 1024, strength: 0.50, steps: 12, guidance_scale: 8.5, guidance_rescale: 0.7, seed: -1 }
  }
];

export function getPreset(name) {
  return PRESETS.find(p => p.name === name) || null;
}
