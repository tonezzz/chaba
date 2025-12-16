const MCP0_BASE = 'https://mcp0.idc1.surf-thailand.com';
const GLAMA_PROVIDER = 'glama';
const MCP0_INVOKE_URL = `${MCP0_BASE}/proxy/${GLAMA_PROVIDER}/invoke`;
const ENTER_PREF_KEY = 'glama_enter_to_send';
const LANGUAGE_PREF_KEY = 'glama_language_preference';
const MODEL_PREF_KEY = 'glama_model_preference';

const statusEl = document.getElementById('status');
const chatLogEl = document.getElementById('chat-log');
const chatForm = document.getElementById('chat-form');
const chatInput = document.getElementById('chat-input');
const sendButton = document.getElementById('send-button');
const attachButton = document.getElementById('attach-button');
const fileInput = document.getElementById('file-input');
const attachmentsEl = document.getElementById('attachments');
const enterToggle = document.getElementById('enter-toggle');
const temperatureInput = document.getElementById('temperature');
const languageSelect = document.getElementById('language-select');
const modelSelect = document.getElementById('model-select');
const template = document.getElementById('message-template');

const LANGUAGE_OPTIONS = [
  { value: 'auto', label: 'Auto detect' },
  { value: 'en', label: 'English' },
  { value: 'th', label: 'ไทย (Thai)' },
  { value: 'es', label: 'Español' },
  { value: 'ja', label: '日本語' },
  { value: 'zh', label: '中文' }
];

const SPEECH_LOCALE_MAP = {
  en: 'en-US',
  th: 'th-TH',
  es: 'es-ES',
  ja: 'ja-JP',
  zh: 'zh-CN'
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const parseMcp0ProxyError = (payload) => {
  if (!payload || typeof payload !== 'object') {
    return 'mcp0_proxy_failed';
  }
  const statusCode = Number(payload?.status_code);
  if (Number.isFinite(statusCode) && statusCode >= 400) {
    const inner = payload?.response;
    const innerDetail =
      (typeof inner?.detail === 'string' && inner.detail) ||
      (typeof inner?.error === 'string' && inner.error) ||
      (typeof inner === 'string' && inner) ||
      '';
    return innerDetail || `provider_http_${statusCode}`;
  }
  if (typeof payload?.detail === 'string' && payload.detail) {
    return payload.detail;
  }
  return 'mcp0_proxy_failed';
};

const invokeMcp0WithRetry = async (invokePayload, { attempts = 3 } = {}) => {
  let lastError = null;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const res = await fetch(MCP0_INVOKE_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(invokePayload)
      });

      let data = null;
      try {
        data = await res.json();
      } catch {
        data = null;
      }

      if (!res.ok) {
        throw new Error(parseMcp0ProxyError(data) || res.statusText || 'mcp0_proxy_failed');
      }

      const embeddedStatus = Number(data?.status_code);
      if (Number.isFinite(embeddedStatus) && embeddedStatus >= 500) {
        throw new Error(parseMcp0ProxyError(data));
      }
      if (Number.isFinite(embeddedStatus) && embeddedStatus >= 400) {
        return { ok: false, data, error: parseMcp0ProxyError(data) };
      }

      return { ok: true, data, error: null };
    } catch (error) {
      lastError = error;
      if (attempt < attempts) {
        await sleep(250 * attempt);
        continue;
      }
    }
  }

  return { ok: false, data: null, error: lastError?.message || 'mcp0_proxy_failed' };
};

const readImageAsDataUrl = async (file) => {
  if (!file.type || !file.type.toLowerCase().startsWith('image/')) {
    return {
      ok: false,
      summary: `Skipped ${file.name}: not an image (${file.type || 'unknown'})`
    };
  }
  if (file.size > MAX_IMAGE_ATTACHMENT_BYTES) {
    return {
      ok: false,
      summary: `Skipped ${file.name}: too large (${formatBytes(file.size)} > ${formatBytes(MAX_IMAGE_ATTACHMENT_BYTES)})`
    };
  }
  return await new Promise((resolve) => {
    const reader = new FileReader();
    reader.onerror = () => resolve({ ok: false, summary: `Skipped ${file.name}: read_failed` });
    reader.onload = () => {
      const result = typeof reader.result === 'string' ? reader.result : '';
      if (!result.startsWith('data:image/')) {
        resolve({ ok: false, summary: `Skipped ${file.name}: invalid_image_data` });
        return;
      }
      resolve({ ok: true, summary: `Attached ${file.name} (${formatBytes(file.size)})`, dataUrl: result });
    };
    reader.readAsDataURL(file);
  });
};

const formatBytes = (bytes) => {
  if (!Number.isFinite(bytes)) return '';
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
};

const renderAttachments = () => {
  if (!attachmentsEl) return;
  attachmentsEl.innerHTML = '';
  if (!selectedAttachments.length) {
    attachmentsEl.hidden = true;
    return;
  }

  selectedAttachments.forEach((file, index) => {
    const chip = document.createElement('div');
    chip.className = 'attachment-chip';

    const label = document.createElement('span');
    label.textContent = `${file.name} (${formatBytes(file.size)})`;

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.setAttribute('aria-label', `Remove ${file.name}`);
    remove.textContent = '×';
    remove.addEventListener('click', () => {
      selectedAttachments.splice(index, 1);
      renderAttachments();
    });

    chip.appendChild(label);
    chip.appendChild(remove);
    attachmentsEl.appendChild(chip);
  });

  attachmentsEl.hidden = false;
};

const readAttachmentAsText = async (file) => {
  const mime = (file.type || '').toLowerCase();
  const isTextLike =
    mime.startsWith('text/') ||
    mime === 'application/json' ||
    mime === 'application/xml' ||
    mime === 'application/javascript' ||
    mime === 'application/x-javascript';

  if (!isTextLike) {
    return {
      ok: false,
      summary: `Skipped ${file.name}: unsupported type (${file.type || 'unknown'})`
    };
  }

  if (file.size > MAX_ATTACHMENT_BYTES) {
    return {
      ok: false,
      summary: `Skipped ${file.name}: too large (${formatBytes(file.size)} > ${formatBytes(MAX_ATTACHMENT_BYTES)})`
    };
  }

  const content = await file.text();
  return {
    ok: true,
    summary: `Attached ${file.name} (${formatBytes(file.size)})`,
    content
  };
};

const buildMessageWithAttachments = async (message) => {
  if (!selectedAttachments.length) {
    return {
      message: message.trim(),
      notes: [],
      userContent: message.trim(),
      imageParts: []
    };
  }

  const notes = [];
  const parts = [message.trim()];
  const imageParts = [];

  for (const file of selectedAttachments) {
    try {
      if (file.type && file.type.toLowerCase().startsWith('image/')) {
        const result = await readImageAsDataUrl(file);
        notes.push(result.summary);
        if (result.ok) {
          imageParts.push({ type: 'image_url', image_url: { url: result.dataUrl } });
        }
        continue;
      }

      const result = await readAttachmentAsText(file);
      notes.push(result.summary);
      if (result.ok) {
        parts.push(`\n\n[Attachment: ${file.name}]\n${result.content}`);
      }
    } catch (error) {
      notes.push(`Skipped ${file.name}: ${error.message || 'read_failed'}`);
    }
  }

  const combinedText = parts.join('\n');
  const userContent = imageParts.length
    ? [{ type: 'text', text: combinedText }, ...imageParts]
    : combinedText;

  return { message: combinedText, notes, userContent, imageParts };
};

const history = [];
const supportsSpeechSynthesis = typeof window !== 'undefined' && 'speechSynthesis' in window;
const selectedAttachments = [];

const MAX_ATTACHMENT_BYTES = 250 * 1024;
const MAX_IMAGE_ATTACHMENT_BYTES = 2 * 1024 * 1024;
const MAX_ATTACHMENTS = 3;
const MODEL_OPTIONS = ['gpt-4.1', 'gpt-4o', 'gpt-4o-mini'];
let selectedModel = (() => {
  try {
    const stored = window.localStorage.getItem(MODEL_PREF_KEY);
    if (stored && typeof stored === 'string' && MODEL_OPTIONS.includes(stored)) {
      return stored;
    }
  } catch {}
  return MODEL_OPTIONS[0];
})();
let selectedLanguage = (() => {
  try {
    const stored = window.localStorage.getItem(LANGUAGE_PREF_KEY);
    if (stored && LANGUAGE_OPTIONS.some((option) => option.value === stored)) {
      return stored;
    }
  } catch {}
  return 'auto';
})();
let activeUtterance = null;

const setStatus = (text, ok = false) => {
  statusEl.textContent = text;
  statusEl.classList.toggle('ok', ok);
};

const formatTime = (date = new Date()) =>
  date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });

const getLanguageLabel = (value) => {
  if (!value) return '';
  const match = LANGUAGE_OPTIONS.find((option) => option.value === value);
  return match ? match.label : value.toUpperCase();
};

const resolveSpeechLocale = (code) => {
  if (!code || code === 'auto') {
    return 'en-US';
  }
  if (code.includes('-')) {
    return code;
  }
  return SPEECH_LOCALE_MAP[code] || 'en-US';
};

const appendMessage = ({ role, content, pending = false, languageCode = null, canSpeak = false }) => {
  const clone = template.content.cloneNode(true);
  const article = clone.querySelector('.message');
  const langLabelEl = clone.querySelector('.message-lang');
  const speakerBtn = clone.querySelector('.message-speaker');
  article.classList.add(role);
  if (pending) article.classList.add('pending');

  clone.querySelector('.message-role').textContent = role === 'user' ? 'You' : 'Glama';
  clone.querySelector('.message-time').textContent = formatTime();
  clone.querySelector('.message-body').textContent = content;

  const langToShow = languageCode || (selectedLanguage !== 'auto' ? selectedLanguage : null);
  if (langLabelEl) {
    if (langToShow) {
      langLabelEl.textContent = getLanguageLabel(langToShow);
      langLabelEl.hidden = false;
    } else {
      langLabelEl.hidden = true;
    }
  }

  if (speakerBtn) {
    const speechText = typeof content === 'string' ? content.trim() : '';
    const enableSpeaker =
      !pending && role === 'assistant' && canSpeak && speechText && supportsSpeechSynthesis;
    if (enableSpeaker) {
      speakerBtn.hidden = false;
      speakerBtn.dataset.speakText = speechText;
      speakerBtn.dataset.speakLang = resolveSpeechLocale(languageCode || selectedLanguage);
    } else {
      speakerBtn.hidden = true;
      speakerBtn.removeAttribute('data-speak-text');
      speakerBtn.removeAttribute('data-speak-lang');
      speakerBtn.classList.remove('is-speaking');
    }
  }

  chatLogEl.appendChild(clone);
  chatLogEl.scrollTop = chatLogEl.scrollHeight;
  return chatLogEl.lastElementChild;
};

const refreshStatus = async () => {
  if (!selectedModel || !MODEL_OPTIONS.includes(selectedModel)) {
    selectedModel = MODEL_OPTIONS[0];
  }
  hydrateModelSelect();
  setStatus('Ready · MCP0', true);
};

const hydrateModelSelect = () => {
  if (!modelSelect) return;
  modelSelect.innerHTML = '';
  MODEL_OPTIONS.forEach((value) => {
    const opt = document.createElement('option');
    opt.value = value;
    opt.textContent = value;
    if (value === selectedModel) {
      opt.selected = true;
    }
    modelSelect.appendChild(opt);
  });
};

const bindModelSelector = () => {
  if (!modelSelect) return;
  modelSelect.addEventListener('change', (event) => {
    selectedModel = event.target.value;
    try {
      localStorage.setItem(MODEL_PREF_KEY, selectedModel);
    } catch {}
  });
};

const sendMessage = async (message) => {
  const { userContent } = await buildMessageWithAttachments(message);
  const temperature = Number(temperatureInput.value);

  const invokePayload = {
    tool: 'chat_completion',
    arguments: {
      messages: [...history, { role: 'user', content: userContent }],
      model: selectedModel,
      max_tokens: 900,
      temperature: Number.isFinite(temperature) ? temperature : 0.2
    }
  };

  const placeholder = appendMessage({
    role: 'assistant',
    content: '…thinking',
    pending: true,
    languageCode: selectedLanguage
  });
  history.push({ role: 'user', content: typeof userContent === 'string' ? userContent : message.trim() });

  try {
    const result = await invokeMcp0WithRetry(invokePayload, { attempts: 3 });
    if (!result.ok) {
      throw new Error(result.error || 'mcp0_proxy_failed');
    }
    const data = result.data;
    placeholder.remove();
    const replyText =
      data?.response?.result?.response ||
      data?.response?.result?.raw?.choices?.[0]?.message?.content ||
      '';
    if (!replyText) {
      throw new Error('empty_response');
    }
    appendMessage({
      role: 'assistant',
      content: replyText,
      languageCode: selectedLanguage,
      canSpeak: true
    });
    history.push({ role: 'assistant', content: replyText });
  } catch (error) {
    console.error('[glama-ui] send failed', error);
    placeholder.remove();
    appendMessage({ role: 'assistant', content: `Error: ${error.message || 'Failed to reach backend'}` });
  }
};

chatForm.addEventListener('submit', (event) => {
  event.preventDefault();
  const message = chatInput.value.trim();
  if (!message) return;
  appendMessage({ role: 'user', content: message, languageCode: selectedLanguage });
  chatInput.value = '';
  sendMessage(message).finally(() => {
    selectedAttachments.splice(0, selectedAttachments.length);
    if (fileInput) fileInput.value = '';
    renderAttachments();
  });
});

if (attachButton && fileInput) {
  fileInput.addEventListener('change', () => {
    const files = Array.from(fileInput.files || []);
    if (!files.length) return;

    for (const file of files) {
      if (selectedAttachments.length >= MAX_ATTACHMENTS) {
        break;
      }
      selectedAttachments.push(file);
    }
    renderAttachments();
  });
}

chatInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey && enterToggle.checked) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

enterToggle.addEventListener('change', () => {
  localStorage.setItem(ENTER_PREF_KEY, enterToggle.checked ? '1' : '0');
});

const initEnterPreference = () => {
  const stored = localStorage.getItem(ENTER_PREF_KEY);
  enterToggle.checked = stored !== '0';
};

const hydrateLanguageSelect = () => {
  if (!languageSelect) return;
  languageSelect.innerHTML = '';
  LANGUAGE_OPTIONS.forEach((option) => {
    const opt = document.createElement('option');
    opt.value = option.value;
    opt.textContent = option.label;
    if (option.value === selectedLanguage) {
      opt.selected = true;
    }
    languageSelect.appendChild(opt);
  });
};

const bindLanguageSelector = () => {
  if (!languageSelect) return;
  languageSelect.addEventListener('change', (event) => {
    selectedLanguage = event.target.value;
    try {
      localStorage.setItem(LANGUAGE_PREF_KEY, selectedLanguage);
    } catch {}
  });
};

const stopSpeaking = () => {
  if (!supportsSpeechSynthesis) return;
  window.speechSynthesis.cancel();
  const activeButton = chatLogEl.querySelector('.message-speaker.is-speaking');
  if (activeButton) {
    activeButton.classList.remove('is-speaking');
  }
  activeUtterance = null;
};

const speakText = (text, locale, buttonEl) => {
  if (!supportsSpeechSynthesis || !text) return;
  stopSpeaking();
  activeUtterance = new SpeechSynthesisUtterance(text);
  activeUtterance.lang = locale || 'en-US';
  activeUtterance.rate = 1;
  if (buttonEl) {
    buttonEl.classList.add('is-speaking');
  }
  activeUtterance.onend = activeUtterance.onerror = () => {
    if (buttonEl) {
      buttonEl.classList.remove('is-speaking');
    }
    activeUtterance = null;
  };
  window.speechSynthesis.speak(activeUtterance);
};

chatLogEl.addEventListener('click', (event) => {
  const speakerBtn = event.target.closest('.message-speaker');
  if (!speakerBtn || speakerBtn.hidden) return;
  const text = speakerBtn.dataset.speakText;
  if (!text) return;
  const lang = speakerBtn.dataset.speakLang || resolveSpeechLocale(selectedLanguage);
  speakText(text, lang, speakerBtn);
});

const init = () => {
  initEnterPreference();
  hydrateLanguageSelect();
  bindLanguageSelector();
  bindModelSelector();
  refreshStatus();
  appendMessage({
    role: 'assistant',
    content: 'Welcome! This panel talks directly to Glama via the new a1.idc1 backend. Ask away when ready.'
  });
};

init();
