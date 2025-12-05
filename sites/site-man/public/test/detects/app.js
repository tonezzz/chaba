const promptSamples = [
  {
    id: 'street',
    label: 'Urban scene audit',
    text: 'Describe the street scene, note weather, people activity, and list vehicles or signage that stand out.'
  },
  {
    id: 'retail',
    label: 'Retail layout check',
    text: 'Summarize the product arrangement and mention any promotional assets or customer interactions visible.'
  },
  {
    id: 'safety',
    label: 'Safety compliance sweep',
    text: 'Inspect for potential hazards, PPE usage, and objects that might block exits or walkways.'
  }
];

const $ = (selector) => document.querySelector(selector);
const detectForm = $('#detectForm');
const browseBtn = $('#browseBtn');
const photoInput = $('#photoInput');
const dropzone = document.querySelector('[data-dropzone]');
const fileHint = $('#fileHint');
const previewWrap = $('#previewWrap');
const previewImage = $('#previewImage');
const promptChipsEl = $('#promptChips');
const promptInput = $('#promptInput');
const statusBanner = $('#statusBanner');
const analyzeBtn = $('#analyzeBtn');
const descriptionOutput = $('#descriptionOutput');
const objectsGrid = $('#objectsGrid');
const rawOutput = $('#rawOutput');
const modelTag = $('#modelTag');
const latencyTag = $('#latencyTag');

let selectedFile = null;
let selectedPromptId = null;

const formatStatus = (text, state = '') => {
  statusBanner.textContent = text;
  statusBanner.classList.remove('ok', 'error');
  if (state === 'ok') statusBanner.classList.add('ok');
  if (state === 'error') statusBanner.classList.add('error');
};

const renderPromptChips = () => {
  promptChipsEl.innerHTML = '';
  promptSamples.forEach((sample) => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'chip';
    chip.textContent = sample.label;
    chip.dataset.promptId = sample.id;
    chip.addEventListener('click', () => selectPrompt(sample.id));
    promptChipsEl.appendChild(chip);
  });
  selectPrompt(promptSamples[0].id);
};

const selectPrompt = (promptId) => {
  const sample = promptSamples.find((p) => p.id === promptId);
  if (!sample) return;
  selectedPromptId = sample.id;
  promptInput.value = sample.text;
  document.querySelectorAll('.chip').forEach((chip) => {
    chip.classList.toggle('active', chip.dataset.promptId === promptId);
  });
};

const updateFileState = (file) => {
  if (!file) {
    selectedFile = null;
    fileHint.textContent = 'No file selected yet.';
    previewWrap.classList.add('hidden');
    previewImage.src = '';
    return;
  }
  selectedFile = file;
  fileHint.textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MB`;
  const reader = new FileReader();
  reader.onload = (event) => {
    previewImage.src = event.target.result;
    previewWrap.classList.remove('hidden');
  };
  reader.readAsDataURL(file);
};

const handleFiles = (files) => {
  if (!files?.length) {
    updateFileState(null);
    return;
  }
  const file = files[0];
  if (!file.type.startsWith('image/')) {
    formatStatus('Please select an image file (jpg, png, heic).', 'error');
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    formatStatus('Image must be 10MB or less.', 'error');
    return;
  }
  updateFileState(file);
  formatStatus('Photo ready. Pick a prompt to continue.');
};

const bindDropzone = () => {
  const prevent = (event) => {
    event.preventDefault();
    event.stopPropagation();
  };
  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach((eventName) => {
    dropzone.addEventListener(eventName, prevent);
  });
  dropzone.addEventListener('dragenter', () => dropzone.classList.add('drag-over'));
  dropzone.addEventListener('dragover', () => dropzone.classList.add('drag-over'));
  dropzone.addEventListener('dragleave', () => dropzone.classList.remove('drag-over'));
  dropzone.addEventListener('drop', (event) => {
    dropzone.classList.remove('drag-over');
    handleFiles(event.dataTransfer.files);
  });
  dropzone.addEventListener('click', () => photoInput.click());
};

const setLoading = (loading) => {
  analyzeBtn.disabled = loading;
  analyzeBtn.textContent = loading ? 'Analyzing…' : 'Run describe + detect';
};

const renderObjects = (objects = []) => {
  objectsGrid.innerHTML = '';
  if (!objects.length) {
    const empty = document.createElement('p');
    empty.className = 'muted';
    empty.textContent = 'No objects returned.';
    objectsGrid.appendChild(empty);
    return;
  }

  objects
    .slice()
    .sort((a, b) => (b.confidence || 0) - (a.confidence || 0))
    .forEach((obj) => {
      const pill = document.createElement('div');
      pill.className = 'object-pill';
      const label = document.createElement('h3');
      label.textContent = obj.label || 'Unknown object';
      const meta = document.createElement('p');
      const conf = typeof obj.confidence === 'number' ? `${(obj.confidence * 100).toFixed(1)}%` : '—';
      const detail = obj.detail ? ` • ${obj.detail}` : '';
      meta.textContent = `Confidence ${conf}${detail}`;
      pill.append(label, meta);
      objectsGrid.appendChild(pill);
    });
};

const handleSubmit = async (event) => {
  event.preventDefault();
  if (!selectedFile) {
    formatStatus('Please upload a photo first.', 'error');
    return;
  }
  const prompt = promptInput.value.trim();
  if (!prompt) {
    formatStatus('Prompt cannot be empty.', 'error');
    return;
  }

  const formData = new FormData();
  formData.append('photo', selectedFile, selectedFile.name);
  formData.append('prompt', prompt);

  formatStatus('Sending image to Glama…');
  setLoading(true);

  try {
    const response = await fetch('/api/detects/analyze', {
      method: 'POST',
      body: formData
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || 'Vision analyze failed');
    }
    const result = await response.json();
    descriptionOutput.textContent = result.description || 'No description returned.';
    renderObjects(result.objects || []);
    rawOutput.textContent = JSON.stringify(result.raw ?? result, null, 2);
    modelTag.textContent = result.model || '—';
    latencyTag.textContent = result.latencyMs ? `${result.latencyMs} ms` : '—';
    formatStatus('Vision analysis complete.', 'ok');
  } catch (error) {
    console.error('Analyze failed', error);
    formatStatus(error.message || 'Vision analysis failed.', 'error');
  } finally {
    setLoading(false);
  }
};

const init = () => {
  renderPromptChips();
  bindDropzone();
  browseBtn?.addEventListener('click', () => photoInput.click());
  photoInput?.addEventListener('change', (event) => handleFiles(event.target.files));
  detectForm?.addEventListener('submit', handleSubmit);
};

init();
