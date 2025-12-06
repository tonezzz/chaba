const LANGUAGE_OPTIONS = [
  { value: 'en', label: 'English (EN)', description: 'Default' },
  { value: 'th', label: 'ไทย (TH)', description: 'ภาษาไทย' }
];

const DEFAULT_LANGUAGE = 'en';

const UI_COPY = {
  default: {
    heroEyebrow: 'Surf Thailand • A1 Vision Utilities',
    heroTitle: 'Photo understanding sandbox',
    heroLede:
      'Drop in a still photo, choose one of the vision prompts, and we’ll send it through our Glama vision endpoint to describe the scene and pinpoint notable objects.',
    langLabel: 'Language',
    uploadHeading: '1. Upload photo',
    uploadBody: 'Single still image, max 10 MB. Works great with portrait or landscape shots.',
    dropTitle: 'Drag & drop photo',
    dropAlt: 'or',
    browseButton: 'browse files',
    fileHintEmpty: 'No file selected yet.',
    promptHeading: '2. Pick a vision brief',
    promptBody: 'Tap a chip to autofill the prompt, or fine-tune in the text box.',
    promptLabel: 'Custom instructions',
    promptPlaceholder: 'Explain what you want the model to focus on…',
    analyzeButtonIdle: 'Run describe + detect',
    analyzeButtonBusy: 'Analyzing…',
    statusWaiting: 'Waiting for your photo…',
    statusPhotoReady: 'Photo ready. Pick a prompt to continue.',
    statusInvalidFile: 'Please select an image file (jpg, png, heic).',
    statusFileTooLarge: 'Image must be 10MB or less.',
    statusNeedPhoto: 'Please upload a photo first.',
    statusNeedPrompt: 'Prompt cannot be empty.',
    statusAnalyzing: 'Sending image to Glama…',
    statusAnalyzeComplete: 'Vision analysis complete.',
    statusAnalyzeFailed: 'Vision analysis failed.',
    summaryHeading: 'Vision summary',
    summaryEmpty: 'No analysis yet.',
    objectsHeading: 'Detected objects',
    objectsEmpty: 'No objects returned.',
    rawHeading: 'Raw payload',
    rawSubheading: 'Direct JSON from the Glama response.',
    rawPlaceholder: '// Awaiting response…'
  },
  th: {
    heroEyebrow: 'เซิร์ฟไทยแลนด์ • ชุดเครื่องมือวิชั่น A1',
    heroTitle: 'สนามทดลองวิเคราะห์ภาพ',
    heroLede:
      'อัปโหลดภาพนิ่ง เลือกพรอมต์วิชั่น แล้วเราจะส่งไปยัง Glama เพื่อบรรยายฉากและเน้นวัตถุสำคัญให้คุณทันที',
    langLabel: 'ภาษา',
    uploadHeading: '1. อัปโหลดภาพ',
    uploadBody: 'รองรับภาพนิ่ง 1 ไฟล์ ขนาดไม่เกิน 10 MB จะเป็นแนวตั้งหรือแนวนอนก็ได้',
    dropTitle: 'ลาก & วางรูปภาพ',
    dropAlt: 'หรือ',
    browseButton: 'เลือกไฟล์',
    fileHintEmpty: 'ยังไม่ได้เลือกไฟล์',
    promptHeading: '2. เลือกโจทย์วิชั่น',
    promptBody: 'แตะชิปเพื่อกรอกพรอมต์อัตโนมัติ หรือปรับแต่งข้อความเอง',
    promptLabel: 'คำสั่งเพิ่มเติม',
    promptPlaceholder: 'อธิบายสิ่งที่อยากให้โมเดลโฟกัส…',
    analyzeButtonIdle: 'สั่งวิเคราะห์ภาพ',
    analyzeButtonBusy: 'กำลังวิเคราะห์…',
    statusWaiting: 'รอรูปภาพจากคุณ…',
    statusPhotoReady: 'ไฟล์พร้อมแล้ว เลือกพรอมต์ต่อได้เลย',
    statusInvalidFile: 'กรุณาเลือกไฟล์ภาพ (jpg, png, heic)',
    statusFileTooLarge: 'ไฟล์ต้องไม่เกิน 10 MB',
    statusNeedPhoto: 'กรุณาอัปโหลดภาพก่อน',
    statusNeedPrompt: 'ห้ามปล่อยพรอมต์ว่าง',
    statusAnalyzing: 'กำลังส่งภาพไปยัง Glama…',
    statusAnalyzeComplete: 'วิเคราะห์ภาพเสร็จแล้ว',
    statusAnalyzeFailed: 'วิเคราะห์ภาพไม่สำเร็จ',
    summaryHeading: 'สรุปผลวิชั่น',
    summaryEmpty: 'ยังไม่มีการวิเคราะห์',
    objectsHeading: 'วัตถุที่ตรวจพบ',
    objectsEmpty: 'ไม่มีวัตถุที่รายงาน',
    rawHeading: 'ข้อมูลดิบ',
    rawSubheading: 'JSON ตรงจากการตอบกลับของ Glama',
    rawPlaceholder: '// รอผลลัพธ์…'
  }
};

const PROMPT_COPY = {
  default: [
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
  ],
  th: [
    {
      id: 'street',
      label: 'ตรวจฉากในเมือง',
      text: 'อธิบายบรรยากาศถนน สภาพอากาศ กิจกรรมของผู้คน และวัตถุหรือป้ายที่โดดเด่น'
    },
    {
      id: 'retail',
      label: 'เช็คร้านค้า/เชลฟ์',
      text: 'สรุปการจัดวางสินค้า ป้ายโปรโมชั่น และพฤติกรรมลูกค้าที่เห็น'
    },
    {
      id: 'safety',
      label: 'ตรวจความปลอดภัย',
      text: 'มองหาความเสี่ยง อุปกรณ์ PPE การกีดขวางทางหนีไฟ หรือสิ่งที่อาจเกิดอันตราย'
    }
  ]
};
PROMPT_COPY.en = PROMPT_COPY.default;

const elements = {
  detectForm: document.getElementById('detectForm'),
  browseBtn: document.getElementById('browseBtn'),
  photoInput: document.getElementById('photoInput'),
  dropzone: document.querySelector('[data-dropzone]'),
  fileHint: document.getElementById('fileHint'),
  previewWrap: document.getElementById('previewWrap'),
  previewImage: document.getElementById('previewImage'),
  promptChips: document.getElementById('promptChips'),
  promptInput: document.getElementById('promptInput'),
  statusBanner: document.getElementById('statusBanner'),
  analyzeBtn: document.getElementById('analyzeBtn'),
  descriptionOutput: document.getElementById('descriptionOutput'),
  objectsGrid: document.getElementById('objectsGrid'),
  rawOutput: document.getElementById('rawOutput'),
  modelTag: document.getElementById('modelTag'),
  latencyTag: document.getElementById('latencyTag'),
  heroEyebrow: document.getElementById('heroEyebrow'),
  heroTitle: document.getElementById('heroTitle'),
  heroLede: document.getElementById('heroLede'),
  langLabel: document.getElementById('langLabel'),
  uploadHeading: document.getElementById('uploadHeading'),
  uploadBody: document.getElementById('uploadBody'),
  dropTitle: document.getElementById('dropTitle'),
  dropAlt: document.getElementById('dropAlt'),
  promptHeading: document.getElementById('promptHeading'),
  promptBody: document.getElementById('promptBody'),
  promptLabel: document.getElementById('promptLabel'),
  summaryHeading: document.getElementById('summaryHeading'),
  objectsHeading: document.getElementById('objectsHeading'),
  rawHeading: document.getElementById('rawHeading'),
  rawSubheading: document.getElementById('rawSubheading'),
  languageSelect: document.getElementById('languageSelect')
};

const state = {
  language: DEFAULT_LANGUAGE,
  promptSamples: [],
  selectedPromptId: null,
  selectedFile: null,
  isAnalyzing: false,
  hasAnalysis: false,
  hasRaw: false,
  hasObjects: false,
  statusKey: 'statusWaiting',
  statusState: '',
  statusOverride: null
};

let promptInputDirty = false;

const getStrings = (lang = state.language) => ({
  ...UI_COPY.default,
  ...(UI_COPY[lang] || {})
});

const t = (key, fallback = '') => {
  if (!key) return fallback;
  const strings = getStrings();
  return strings[key] ?? fallback ?? key;
};

const getPromptSet = () => PROMPT_COPY[state.language] || PROMPT_COPY.default;

const setStatus = (key, stateClass = '', overrideText) => {
  state.statusKey = key || 'statusWaiting';
  state.statusState = stateClass || '';
  state.statusOverride = overrideText ?? null;

  const text = overrideText || t(state.statusKey);
  if (!elements.statusBanner) return;
  elements.statusBanner.textContent = text;
  elements.statusBanner.classList.remove('ok', 'error');
  if (state.statusState === 'ok') elements.statusBanner.classList.add('ok');
  if (state.statusState === 'error') elements.statusBanner.classList.add('error');
};

const refreshStatus = () => setStatus(state.statusKey, state.statusState, state.statusOverride);

const setLoading = (loading) => {
  state.isAnalyzing = loading;
  if (!elements.analyzeBtn) return;
  elements.analyzeBtn.disabled = loading;
  elements.analyzeBtn.textContent = loading ? t('analyzeButtonBusy') : t('analyzeButtonIdle');
};

const resetOutputs = () => {
  state.hasAnalysis = false;
  state.hasRaw = false;
  state.hasObjects = false;
  if (elements.descriptionOutput) elements.descriptionOutput.textContent = t('summaryEmpty');
  if (elements.rawOutput) elements.rawOutput.textContent = t('rawPlaceholder');
  if (elements.objectsGrid) {
    elements.objectsGrid.innerHTML = '';
    const empty = document.createElement('p');
    empty.className = 'muted';
    empty.textContent = t('objectsEmpty');
    elements.objectsGrid.appendChild(empty);
  }
  if (elements.modelTag) elements.modelTag.textContent = '—';
  if (elements.latencyTag) elements.latencyTag.textContent = '—';
};

const updateFileState = (file) => {
  state.selectedFile = file || null;
  if (!file) {
    if (elements.fileHint) elements.fileHint.textContent = t('fileHintEmpty');
    if (elements.previewWrap) elements.previewWrap.classList.add('hidden');
    if (elements.previewImage) elements.previewImage.src = '';
    resetOutputs();
    return;
  }

  if (elements.fileHint) {
    const sizeMb = (file.size / 1024 / 1024).toFixed(2);
    elements.fileHint.textContent = `${file.name} · ${sizeMb} MB`;
  }
  const reader = new FileReader();
  reader.onload = (event) => {
    if (elements.previewImage) elements.previewImage.src = event.target.result;
    if (elements.previewWrap) elements.previewWrap.classList.remove('hidden');
  };
  reader.readAsDataURL(file);
};

const renderObjects = (objects = []) => {
  if (!elements.objectsGrid) return;
  elements.objectsGrid.innerHTML = '';
  if (!objects.length) {
    const empty = document.createElement('p');
    empty.className = 'muted';
    empty.textContent = t('objectsEmpty');
    elements.objectsGrid.appendChild(empty);
    state.hasObjects = false;
    return;
  }
  state.hasObjects = true;
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
      elements.objectsGrid.appendChild(pill);
    });
};

const renderPromptChips = () => {
  if (!elements.promptChips) return;
  elements.promptChips.innerHTML = '';
  state.promptSamples = getPromptSet();
  state.promptSamples.forEach((sample) => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'chip';
    chip.dataset.promptId = sample.id;
    chip.textContent = sample.label;
    chip.addEventListener('click', () => selectPrompt(sample.id, true));
    elements.promptChips.appendChild(chip);
  });
  const fallbackId = state.promptSamples[0]?.id;
  if (fallbackId) {
    selectPrompt(fallbackId, false);
  }
};

const selectPrompt = (promptId, userInitiated = false) => {
  const sample = state.promptSamples.find((entry) => entry.id === promptId);
  if (!sample) return;
  state.selectedPromptId = sample.id;
  if (!promptInputDirty || userInitiated) {
    if (elements.promptInput) elements.promptInput.value = sample.text;
    promptInputDirty = false;
  }
  if (elements.promptChips) {
    elements.promptChips.querySelectorAll('.chip').forEach((chip) => {
      chip.classList.toggle('active', chip.dataset.promptId === sample.id);
    });
  }
};

const handleFiles = (files) => {
  if (!files?.length) {
    updateFileState(null);
    setStatus('statusWaiting');
    return;
  }
  const file = files[0];
  if (!file.type.startsWith('image/')) {
    setStatus('statusInvalidFile', 'error');
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    setStatus('statusFileTooLarge', 'error');
    return;
  }
  updateFileState(file);
  setStatus('statusPhotoReady');
};

const bindDropzone = () => {
  if (!elements.dropzone) return;
  const prevent = (event) => {
    event.preventDefault();
    event.stopPropagation();
  };
  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach((eventName) => {
    elements.dropzone.addEventListener(eventName, prevent);
  });
  elements.dropzone.addEventListener('dragenter', () => elements.dropzone.classList.add('drag-over'));
  elements.dropzone.addEventListener('dragover', () => elements.dropzone.classList.add('drag-over'));
  elements.dropzone.addEventListener('dragleave', () => elements.dropzone.classList.remove('drag-over'));
  elements.dropzone.addEventListener('drop', (event) => {
    elements.dropzone.classList.remove('drag-over');
    handleFiles(event.dataTransfer.files);
  });
  elements.dropzone.addEventListener('click', () => elements.photoInput?.click());
};

const handleSubmit = async (event) => {
  event.preventDefault();
  if (!state.selectedFile) {
    setStatus('statusNeedPhoto', 'error');
    return;
  }
  const prompt = elements.promptInput?.value?.trim();
  if (!prompt) {
    setStatus('statusNeedPrompt', 'error');
    return;
  }

  const formData = new FormData();
  formData.append('photo', state.selectedFile, state.selectedFile.name);
  formData.append('prompt', prompt);

  setStatus('statusAnalyzing');
  setLoading(true);

  try {
    const response = await fetch('/test/detects/api/analyze', {
      method: 'POST',
      body: formData
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || 'Vision analyze failed');
    }
    const result = await response.json();
    state.hasAnalysis = true;
    state.hasRaw = true;
    if (elements.descriptionOutput) {
      elements.descriptionOutput.textContent = result.description || t('summaryEmpty');
    }
    renderObjects(result.objects || []);
    if (elements.rawOutput) {
      elements.rawOutput.textContent = JSON.stringify(result.raw ?? result, null, 2);
    }
    if (elements.modelTag) {
      elements.modelTag.textContent = result.model || '—';
    }
    if (elements.latencyTag) {
      elements.latencyTag.textContent = result.latencyMs ? `${result.latencyMs} ms` : '—';
    }
    setStatus('statusAnalyzeComplete', 'ok');
  } catch (error) {
    console.error('Analyze failed', error);
    const detail = error?.message && error.message !== 'Vision analyze failed' ? error.message : null;
    setStatus('statusAnalyzeFailed', 'error', detail || undefined);
  } finally {
    setLoading(false);
  }
};

const applyLocaleToUI = () => {
  const pairs = [
    [elements.heroEyebrow, 'heroEyebrow'],
    [elements.heroTitle, 'heroTitle'],
    [elements.heroLede, 'heroLede'],
    [elements.langLabel, 'langLabel'],
    [elements.uploadHeading, 'uploadHeading'],
    [elements.uploadBody, 'uploadBody'],
    [elements.dropTitle, 'dropTitle'],
    [elements.promptHeading, 'promptHeading'],
    [elements.promptBody, 'promptBody'],
    [elements.promptLabel, 'promptLabel'],
    [elements.summaryHeading, 'summaryHeading'],
    [elements.objectsHeading, 'objectsHeading'],
    [elements.rawHeading, 'rawHeading'],
    [elements.rawSubheading, 'rawSubheading']
  ];
  pairs.forEach(([el, key]) => {
    if (el) el.textContent = t(key);
  });
  if (elements.dropAlt) elements.dropAlt.textContent = t('dropAlt');
  if (elements.browseBtn) elements.browseBtn.textContent = t('browseButton');
  if (elements.promptInput) elements.promptInput.placeholder = t('promptPlaceholder');
  if (!state.selectedFile && elements.fileHint) elements.fileHint.textContent = t('fileHintEmpty');
  if (!state.hasAnalysis && elements.descriptionOutput) elements.descriptionOutput.textContent = t('summaryEmpty');
  if (!state.hasRaw && elements.rawOutput) elements.rawOutput.textContent = t('rawPlaceholder');
  if (!state.hasObjects) renderObjects([]);
  setLoading(state.isAnalyzing);
};

const populateLanguageSelect = () => {
  if (!elements.languageSelect) return;
  elements.languageSelect.innerHTML = '';
  LANGUAGE_OPTIONS.forEach((opt) => {
    const option = document.createElement('option');
    option.value = opt.value;
    option.textContent = `${opt.label} — ${opt.description}`;
    if (opt.value === state.language) option.selected = true;
    elements.languageSelect.appendChild(option);
  });
};

const setLanguage = (lang) => {
  const exists = LANGUAGE_OPTIONS.some((entry) => entry.value === lang);
  state.language = exists ? lang : DEFAULT_LANGUAGE;
  document.documentElement.lang = state.language;
  try {
    localStorage.setItem('detectsLanguage', state.language);
  } catch {
    /* ignore */
  }
  promptInputDirty = false;
  state.selectedPromptId = null;
  populateLanguageSelect();
  renderPromptChips();
  applyLocaleToUI();
  refreshStatus();
};

const initLanguageSwitcher = () => {
  if (!elements.languageSelect) return;
  elements.languageSelect.addEventListener('change', (event) => {
    setLanguage(event.target.value);
  });
};

const init = () => {
  bindDropzone();
  elements.browseBtn?.addEventListener('click', () => elements.photoInput?.click());
  elements.photoInput?.addEventListener('change', (event) => handleFiles(event.target.files));
  elements.detectForm?.addEventListener('submit', handleSubmit);
  elements.promptInput?.addEventListener('input', () => {
    promptInputDirty = true;
  });

  const stored = (() => {
    try {
      return localStorage.getItem('detectsLanguage');
    } catch {
      return null;
    }
  })();
  setLanguage(stored || DEFAULT_LANGUAGE);
  setStatus('statusWaiting');
  initLanguageSwitcher();
};

init();
